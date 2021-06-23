#!/usr/bin/env python3
# Copyright 2021 dmitriis
# See LICENSE file for licensing details.

import logging

from jinja2 import Environment, FileSystemLoader

from ops.charm import CharmBase
from ops.framework import StoredState
from ops.main import main
from ops.model import ActiveStatus
from ops.pebble import ChangeError

from cluster import KnotCluster

logger = logging.getLogger(__name__)


class KnotOperator(CharmBase):

    _stored = StoredState()

    INITIAL_CONFIG_PATH = '/tmp/initial.conf'
    INCLUDE_CONFIG_PATH = '/tmp/include.conf'
    FUNCTIONS_PATH = '/opt/functions.sh'
    CONFIG_SET_PATH = '/opt/config-set.sh'

    def __init__(self, *args):
        super().__init__(*args)
        self.framework.observe(self.on.knot_pebble_ready, self._on_knot_pebble_ready)
        self.framework.observe(self.on.config_changed, self._on_config_changed)
        self.framework.observe(self.on.add_zone_action, self._on_add_zone_action)
        self.framework.observe(self.on.set_zone_action, self._on_set_zone_action)
        self.framework.observe(self.on.set_zone_remotes_action, self._on_set_zone_remotes_action)

        self._stored.set_default(layers_added=False)
        self._template_env = None

        self.cluster = KnotCluster(self, 'knot-cluster')
        self.framework.observe(self.cluster.on.cluster_changed, self._on_cluster_changed)

    def _start_oneshot_service(self, container, service_name):
        try:
            container.start(service_name)
        except ChangeError as e:
            if not (e.change.kind == 'start' and e.change.status == 'Error'
                    and 'cannot start service: exited quickly with code 0' in e.err):
                raise Exception('failed to start a one-shot service') from e

    def _push_template(self, container, template_name, target_path, context={}):
        if self._template_env is None:
            self._template_env = Environment(loader=FileSystemLoader(
                f'{self.charm_dir}/templates'))
        container.push(
            target_path,
            self._template_env.get_template(template_name).render(**context),
            make_dirs=True
        )

    def _on_knot_pebble_ready(self, event):
        """Define and start a workload using the Pebble API.


        Learn more about Pebble layers at https://github.com/canonical/pebble
        """
        self.framework.breakpoint('knot-pebble-ready')
        # Define an initial Pebble layer configuration
        pebble_layer = {
            'summary': 'knot layer',
            'description': 'pebble config layer for knot',
            'services': {
                'knot-ensure-confdb': {
                    'override': 'replace',
                    'summary': 'ensure that the Knot configuration database exists',
                    'command': 'bash -c "knotc --confdb /storage/confdb conf-check ||'
                               ' (knotc --confdb /storage/confdb -f -v conf-init &&'
                               f' knotc conf-import {self.INITIAL_CONFIG_PATH})"',
                    'startup': 'disabled',
                },
                'knot-conf-include': {
                    'override': 'replace',
                    'summary': 'Include a set of configuration values in a config transaction',
                    'command': 'bash -c "knotc conf-begin &&'
                               f' knotc conf-set include {self.INCLUDE_CONFIG_PATH} &&'
                                ' knotc conf-commit"',
                    'startup': 'disabled',
                },
                'knot-conf-set': {
                    'override': 'replace',
                    'summary': 'Include a set of configuration values in a config transaction',
                    'command': f'bash {self.CONFIG_SET_PATH}',
                    'startup': 'disabled',
                },
                'knot': {
                    'override': 'replace',
                    'summary': 'Start knotd',
                    'command': 'knotd --confdb /storage/confdb -v',
                    'startup': 'enabled',
                },
            },
        }

        container = event.workload
        # Add initial Pebble config layer using the Pebble API
        container.add_layer('knot', pebble_layer, combine=True)
        self._stored.layers_added = True

        # Push the initial config file for knot to use. This is to do a direct import
        # of initial state to the configuration database. Changes to the set of addresses
        # on which knot needs to listen require a restart. Starting knot without any
        # of those addresses leads to an assertion failure on conf-commit setting
        # those addresses.
        # https://github.com/CZ-NIC/knot/blob/v3.0.6/src/knot/server/server.c#L817
        self._push_template(container, 'initial-config.conf.j2', self.INITIAL_CONFIG_PATH)

        # Push the script with auxiliary functions to the knot container.
        self._push_template(container, 'functions.sh.j2', self.FUNCTIONS_PATH)
        self._start_oneshot_service(container, 'knot-ensure-confdb')

        if not container.get_service('knot').is_running():
            logger.info('Autostarting knot')
            container.autostart()

        self._apply_config_change(container)

        self.unit.status = ActiveStatus('Knot DNS server is ready')

    def _apply_config_change(self, container):
        context = {'remote_servers': self.model.config['remote-servers'].split()}
        self._push_template(container, 'config-changed.sh.j2', self.CONFIG_SET_PATH, context)

        self._start_oneshot_service(container, 'knot-conf-set')

    def _on_config_changed(self, event):
        if not self._stored.layers_added:
            return

        container = self.unit.get_container("knot")
        services = container.get_plan().to_dict().get("services", {})
        if 'knot' not in services or not container.get_service('knot').is_running():
            event.defer()

        self._apply_config_change(container)

    def _on_cluster_changed(self, event):
        if not self._stored.layers_added:
            return

        zone_records = self.cluster.zone_records()
        for zone, zone_records in zone_records.items():
            self._set_zone(zone, zone_records)

        zone_remotes = self.cluster.zone_remotes()
        for zone, remote_servers in zone_remotes.items():
            self._set_zone_remotes(zone, remote_servers)

    def _on_add_zone_action(self, event):
        if not self.model.unit.is_leader():
            logger.warning('Did not execute add-zone as this is not a leader unit.')
            event.fail('Cannot run this action on a non-leader unit.')
            return
        zone = event.params['zone']
        self.cluster.update_zones(zone, [])

    def _on_set_zone_action(self, event):
        if not self.model.unit.is_leader():
            logger.warning('Did not execute set-zone as this is not a leader unit.')
            event.fail('Cannot run this action on a non-leader unit.')
            return
        params = event.params
        zone = params['zone']
        rr = {
            'owner': params['owner'],
            'ttl': params['ttl'],
            'type': params['type'],
            'rdata': params['rdata'],
        }
        self.cluster.update_zones(zone, [rr])

    def _set_zone(self, zone, resource_records=[]):
        """

        :param str zone: The zone to add or modify.
        :param resource_records: The list of RRs to set (may be empty).
        :type resource_records: list[dict()]
        """
        self.framework.breakpoint()
        container = self.unit.get_container("knot")
        self._push_template(container, 'set-zone.sh.j2', self.CONFIG_SET_PATH,
                            {'zone': zone, 'resource_records': resource_records})
        self._start_oneshot_service(container, 'knot-conf-set')

    def _on_set_zone_remotes_action(self, event):
        if not self.model.unit.is_leader():
            logger.warning('Did not execute set-zone-remotes as this is not a leader unit.')
            event.fail('Cannot run this action on a non-leader unit.')
            return

        if not self.cluster.is_established:
            logger.warning('Did not execute set-zone-remotes the peer relation'
                           ' has not been created yet.')
            event.fail('Cannot run this action before the cluster relation is created.')
            return

        zone = event.params['zone']
        remote_servers = event.params['remote-servers']
        # Notify other units that they should set remote servers for a zone.
        self.cluster.update_zone_remotes(zone, remote_servers)
        # Set zone remotes for the leader unit itself.
        self._set_zone_remotes(zone, remote_servers)

    def _set_zone_remotes(self, zone, remote_servers):
        container = self.unit.get_container("knot")
        remote_name = f'{zone.lower()}_remote'
        self._push_template(container, 'enable-zone-proxy.sh.j2', self.CONFIG_SET_PATH,
                            {'remote_servers': remote_servers, 'zone': zone,
                             'remote_name': remote_name})
        self._start_oneshot_service(container, 'knot-conf-set')


if __name__ == '__main__':
    main(KnotOperator)
