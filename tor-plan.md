# ToR switch configuration demo plan

## Current status

This plan is not yet verified end-to-end. See the
[lessons learned](demo/tor-lessons-learned.md) for confirmed lifecycle
restrictions, the mapping failure, SSH diagnosis, and readiness checks.
Establish port mappings before hosts become available; tenant VLAN tags
are not required to appear during the idle lifecycle.

## Purpose

Demonstrate declarative switch-port configuration as part of bare-metal
provisioning, using BMO's `IronicNetworking` feature:

```text
BareMetalSwitch + HostNetworkAttachment + BMH networkInterfaces
    -> Ironic port configuration -> networking-generic-switch -> OVS
```

The use case is assigning a host's workload NIC to its intended network
before provisioning, without manually configuring the switch port. Guest
IP configuration remains a separate responsibility.

See [the demo guide](demo/tor-networking.md) for configuration examples.

## Supported lifecycle

Upstream BMO commit `ed91ef80ce226a6bdd23b8794990d0008a07f0ee` permits
existing switch-port updates only while a BMH is `registering` or
`available`. It does not apply these updates to a `provisioned` host.

- [State gate](https://github.com/metal3-io/baremetal-operator/blob/ed91ef80ce226a6bdd23b8794990d0008a07f0ee/pkg/provisioner/provisioner.go#L108)
- [Ironic call site](https://github.com/metal3-io/baremetal-operator/blob/ed91ef80ce226a6bdd23b8794990d0008a07f0ee/pkg/provisioner/ironic/register.go#L192)

`IronicNetworking` enables switch integration; it is not a live-update
flag. Recheck these restrictions when using a different BMO revision.

This demo does not require experimental live-update code, tagged-only
trunk support, or manual OVS VLAN commands.

## Topology and scope

```text
VM1 third NIC                         VM2 third NIC
10.30.0.11/24                          10.30.0.12/24
       |                                     |
       +-- access VLAN 3 -- labsw0 -- access VLAN 3
```

- Use the two normal dev-env guests and their dedicated third NICs.
- Preserve provisioning and external interfaces, addresses, and routes.
- Match NICs by their inspected MAC addresses and verify their OVS tap
  names; do not assume a guest interface name.
- Guests send untagged frames on the third NIC. OVS assigns them to
  access VLAN 3. No guest VLAN subinterface is needed.
- No uplink, routing, DHCP, default gateway, or LLDP is required on the
  test network.
- Verify that the chosen test subnet does not overlap existing routes.

## Preparation

1. Use a dedicated Metal3 development VM with `USE_IRSO=true`,
   `ENABLE_TOR_DEMO=true`, and at least two nodes.
1. Configure the third NICs before VM creation. Do not rerun VM setup
   against existing guests to retrofit NICs or regenerate their MACs.
1. Verify BMO's `IronicNetworking` gate, the Ironic networking service,
   and its switch configuration and credentials mounts.
1. Verify SSH authentication and direct `ovs-vsctl` access from the
   networking service using the actual lab credential and a verified
   host key. A reachable SSH port alone is not sufficient.
1. Let inspection complete and verify both BMHs are `available`.

If the lab already has provisioned hosts, stop here. Changing their BMH
network intent does not apply the desired switch configuration with the
verified upstream implementation. Reusing those hosts requires a
separately approved deprovisioning/reprovisioning procedure; do not
delete the target cluster or restart setup implicitly.

## Demonstration

1. Declare `BareMetalSwitch` for `labsw0` and its dedicated credentials.
1. Create an access-mode `tenant-vlan3` HostNetworkAttachment in the BMH
   namespace with `nativeVLAN: 3`.
1. Add only each third NIC's `networkInterfaces` entry, referencing the
   attachment and its verified `switchPort` identity.
1. First verify that Ironic already has the correct switch-port mappings.
   If not, stop: adding the mapping while available was rejected in our lab.
1. While both BMHs remain `available`, wait for valid network interfaces
   and matching applied attachment status.
1. Inspect Ironic's `extra.switchport` and `local_link_connection`, and
   record the actual OVS port state. Tenant VLAN 3 need not be applied
   while available. Validation or applied status alone is not proof of
   successful switch programming.
1. Provision the target cluster through the normal dev-env scripts,
   explicitly selecting the desired `IMAGE_OS`.
1. After both guest operating systems boot, verify the OVS tags again.
   If tap recreation lost the VLAN, report the failure; do not manually
   restore tags or claim automatic reconciliation.
1. Configure persistent test addresses only on the third NICs, without
   a gateway or DNS changes.
1. Verify routing and bounded pings in both directions using the test
   interface/source address.

## Acceptance criteria

| Evidence | Expected result |
|----------|-----------------|
| BMH state when intent is applied | `available` |
| BMO network validation | `NetworkInterfacesValid=True` |
| BMO applied status | Correct third NIC and VLAN attachment |
| Ironic port | Correct switch ID, port ID, and access VLAN 3 |
| OVS ports after tenant configuration is applied | Both tags are `3` |
| Guest routing | Test traffic uses the third NIC and test IP |
| Bounded ping in both directions | Success |
| Existing networks | Provisioning and external configuration unchanged |

No live VLAN 3-to-4 switching or guest-restart recovery is an acceptance
claim for this demo. Stable tap names do not preserve VLAN configuration
when libvirt recreates a port.

## Cleanup and validation

Follow [the guide's cleanup procedure](demo/tor-networking.md#cleanup).
Removing BMH intent while a host is provisioned is not proof of
switch-port cleanup. Coordinate any deprovisioning separately and keep
the switch credentials available until cleanup has been verified.

Static checks:

```bash
make lint
python3 -m unittest discover -s hack -p 'test_tor_demo.py'
python3 -m unittest discover -s hack -p 'test_kind_network.py'
```

These checks do not prove live switch programming or guest connectivity.
Document those results separately after running the approved lab workflow.
