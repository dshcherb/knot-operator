import json

from ops.framework import Object, StoredState, ObjectEvents, EventBase, EventSource


class ClusterChanged(EventBase):
    """An event raised by KnotCluster when cluster-wide settings change.
    """


class KnotClusterEvents(ObjectEvents):
    cluster_changed = EventSource(ClusterChanged)


class KnotCluster(Object):

    on = KnotClusterEvents()
    _stored = StoredState()

    def __init__(self, charm, relation_name):
        super().__init__(charm, relation_name)
        self._relation_name = relation_name
        self._relation = self.framework.model.get_relation(self._relation_name)

        self.framework.observe(charm.on[relation_name].relation_created, self._on_created)
        self.framework.observe(charm.on[relation_name].relation_changed, self._on_changed)

    def _on_created(self, event):
        self._notify_cluster_changed()

    def _on_changed(self, event):
        self._notify_cluster_changed()

    def _notify_cluster_changed(self):
        self.on.cluster_changed.emit()

    @property
    def is_established(self):
        return self._relation is not None

    def update_zones(self, zone, resource_records=[]):
        """Update a list of zones to be maintained cluster-wide.

        :param str zone: The zone to add or modify.
        :param resource_records: The list of RRs to set (may be empty).
        :type resource_records: list[dict()]
        """
        if not self.framework.model.unit.is_leader():
            raise RuntimeError('cannot update zones from a non-leader unit')

        app_data = self._relation.data[self.model.app]
        zone_records_json = app_data.get('zone-records')
        if zone_records_json:
            zone_records = json.loads(zone_records_json)
            if not zone_records:
                zone_records = {
                    zone: resource_records
                }
            if not zone_records.get(zone):
                zone_records[zone] = resource_records
            else:
                zone_records[zone].extend(resource_records)
        else:
            zone_records = {
                zone: resource_records
            }
        app_data['zone-records'] = json.dumps(zone_records)

    def zone_records(self):
        if not self.is_established:
            raise RuntimeError('unable to retrieve zone remotes - peer relation does not exist')

        app_data = self._relation.data[self.model.app]
        zone_records_json = app_data.get('zone-records')
        if zone_records_json:
            return json.loads(zone_records_json)
        else:
            return dict()

    def update_zone_remotes(self, zone, remote_servers):
        """Update the cluster-wide list of DNS proxy servers for a given zone."""
        if not self.framework.model.unit.is_leader():
            raise RuntimeError('cannot update zone proxies from a non-leader unit')

        # Not specifying a zone is invalid, however, an empty list of proxy servers is OK.
        if not zone:
            raise RuntimeError(f'invalid zone parameter specified: {zone}')
        if not isinstance(remote_servers, list):
            raise RuntimeError(f'proxy_servers must be a list, got: {type(remote_servers)}')

        app_data = self._relation.data[self.model.app]
        zone_remotes_json = app_data.get('zone-remotes')
        if zone_remotes_json:
            zone_remotes = json.loads(zone_remotes_json)
            zone_remotes[zone] = remote_servers
        else:
            zone_remotes = {
                zone: remote_servers
            }
        app_data['zone-remotes'] = json.dumps(zone_remotes)

    def zone_remotes(self):
        if not self.is_established:
            raise RuntimeError('unable to retrieve zone remotes - peer relation does not exist')

        app_data = self._relation.data[self.model.app]
        zone_remotes_json = app_data.get('zone-remotes')
        if zone_remotes_json:
            return json.loads(zone_remotes_json)
        else:
            return dict()
