# knot-operator

## Description

An operator that manages the lifecycle of the Knot DNS server which is an
authoritative domain name service implementation.

https://www.knot-dns.cz/docs/latest/html/introduction.html

Knot DNS is not a caching DNS server - for those purposes Knot Resolver should be
used instead. However, Knot DNS is able to act as a DNS proxy:

https://www.knot-dns.cz/docs/latest/html/modules.html?highlight=proxy#dnsproxy-tiny-dns-proxy

## Usage

The `knot-operator` charm deploys Knot DNS on top of Kubernetes:

    juju deploy --channel=beta \
        --resource knot-image=cznic/knot
        knot-operator

By default Knot DNS does not have any zones configured and does not proxy DNS requests for any zone.

It is possible to configure DNS proxying for all zones using the `remote-servers` config option.

### Adding New Units and Scaling

`knot-operator` supports running multiple units side by side and applying the necessary configuration
to all of the running units.

To add a unit to a deployed application use:

    juju add-unit knot-operator

To scale the application to have a particular number of units use:

    juju scale-application knot-operator 3

### Runtime Configuration Changes

`knot-operator` uses configuration database transactions supported by Knot DNS to apply configuration
settings which does not result in DNS service restarts.

### Default Proxying Configuration

The `remote-servers` config option can be used to specify a space-separated list of DNS servers to
proxy client requests to by default for all zones.

    juju config knot-operator remote-servers='192.0.2.42 192.0.2.24'

To undo the effect of this configuration change across all units use the following command:

    juju config knot-operator --reset remote-servers

### Proxying for Individual Zones

An action can be run on a leader unit to set up proxying to remote servers for a particular zone:

    juju run-action knot-operator/leader set-zone-remotes \
                                         zone=com \
                                         remote-servers="[192.0.2.42, 192.0.2.24]"

The leader unit sets appropriate peer application relation settings in order to make
existing and new units pick up the remote servers set by an action at some point.

In order to remove proxying for a particular zone set the list of remote servers for it to an empty list:

    juju run-action knot-operator/leader set-zone-remotes \
                                         zone=com \
                                         remote-servers="[]"


### Configuring Resource Records for a Zone

Use `add-zone` and `set-zone` actions to add zones and update resource records (RRs) in them. The following
set of actions will configure the example zone with a single name server.

    juju run-action knot-operator/leader set-zone zone=example.com owner='"@"' \
                                                  ttl=7200 type=SOA \
                                                  rdata='ns hostmaster 1 86400 900 691200 3600'
    juju run-action knot-operator/leader set-zone zone=example.com owner=ns ttl=3600 type=A \
                                                  rdata=`juju run --unit knot-operator/leader 'network-get --bind-address knot-cluster'`
    juju run-action knot-operator/leader set-zone zone=example.com owner=IN ttl=86400 type=NS rdata=ns


If multiple units of Knot DNS are present, resource records will be replicated to those automatically. The
same applies to new units added after the action is run.

## Known Limitations and Future Work

At the moment primary and secondary relationships are not established between DNS servers in the cluster
and all resource records are applied to all units via peer application relation data. This could be changed
to instead rely on zone transfers and DNS NOTIFY mechanisms instead and to have just one server at the
top of the zone transfer dependency graph as specified in the zone's SOA MNAME field, see:
https://datatracker.ietf.org/doc/html/rfc1996#section-2

This would require selecting and tracking primary servers for each configured zone and adjusting those
as units are brought down or added. A leader unit could be an arbiter in that process.

## Developing

Create and activate a virtualenv with the development requirements:

    virtualenv -p python3 venv
    source venv/bin/activate
    pip install -r requirements-dev.txt

## Testing

The Python operator framework includes a very nice harness for testing
operator behaviour without full deployment. Just `run_tests`:

    ./run_tests
