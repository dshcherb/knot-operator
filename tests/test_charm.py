# Copyright 2021 dmitriis
# See LICENSE file for licensing details.
#
# Learn more about testing at: https://juju.is/docs/sdk/testing

import unittest

from unittest.mock import patch, call

from charm import KnotOperator
from ops.testing import Harness


class TestCharm(unittest.TestCase):
    def setUp(self):
        self.harness = Harness(KnotOperator)
        self.addCleanup(self.harness.cleanup)
        self.harness.begin()

    def test_knot_pebble_ready(self):
        initial_plan = self.harness.get_container_pebble_plan("knot")
        self.assertEqual(initial_plan.to_yaml(), "{}\n")
        expected_plan = {
            'services': {
                'knot-ensure-confdb': {
                    'override': 'replace',
                    'summary': 'ensure that the Knot configuration database exists',
                    'command': 'bash -c "knotc --confdb /storage/confdb conf-check ||'
                               ' (knotc --confdb /storage/confdb -f -v conf-init &&'
                               f' knotc conf-import {KnotOperator.INITIAL_CONFIG_PATH})"',
                    'startup': 'disabled',
                },
                'knot-conf-include': {
                    'override': 'replace',
                    'summary': 'Include a set of configuration values in a config transaction',
                    'command': 'bash -c "knotc conf-begin &&'
                               f' knotc conf-set include {KnotOperator.INCLUDE_CONFIG_PATH} &&'
                                ' knotc conf-commit"',
                    'startup': 'disabled',
                },
                'knot-conf-set': {
                    'override': 'replace',
                    'summary': 'Include a set of configuration values in a config transaction',
                    'command': f'bash {KnotOperator.CONFIG_SET_PATH}',
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
        container = self.harness.model.unit.get_container("knot")
        with patch.object(self.harness.charm, '_push_template'):
            self.harness.charm.on.knot_pebble_ready.emit(container)
            self.harness.charm._push_template.assert_has_calls([
                call(container, 'initial-config.conf.j2', '/tmp/initial.conf'),
                call(container, 'functions.sh.j2', KnotOperator.FUNCTIONS_PATH),
            ])
        updated_plan = self.harness.get_container_pebble_plan("knot").to_dict()
        self.assertEqual(expected_plan, updated_plan)

    def test_config_changed(self):
        self.harness.update_config({"remote-servers": "1.1.1.1 8.8.8.8"})
