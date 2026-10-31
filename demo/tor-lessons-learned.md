# ToR networking demo: lessons learned

Findings recorded on 2026-10-31. This is an investigation record, not a
verified end-to-end runbook.

## What we want to demonstrate

Users declare a workload NIC's switch VLAN through Kubernetes. BMO passes
the intent to Ironic; Ironic's networking service uses
networking-generic-switch to configure the switch port during the host
lifecycle. IrSO deploys and configures the Ironic services.

The intended audience flow is:

```text
Inspect host and discover mapping
    -> select VLAN attachment while available
    -> provision
    -> verify switch VLAN and third-NIC connectivity
```

Guest IP configuration is separate from switch VLAN configuration.
Provisioning and external NICs must remain unchanged.

This flow has not passed an end-to-end test in our lab. We must not present
it as a working demo yet.

## Mapping and VLAN intent are different

A mapping identifies the switch port connected to a NIC:

```text
node-0 third NIC MAC 00:2b:d8:32:19:cf -> labsw0 -> m3tor0
node-1 third NIC MAC 00:2b:d8:32:19:d3 -> labsw0 -> m3tor1
```

Ironic stores this identity in `local_link_connection`. VLAN intent is
stored separately in the port's `extra.switchport`.

Our update supplied both identity and VLAN intent after inspection.
Ironic rejected the identity change while the hosts were `available`.
Because they were sent in one port PATCH, the combined update failed.
This was not proof that all VLAN updates are prohibited.

## Lifecycle restrictions

The verified implementations have two separate gates:

- BMO permits existing switch-port configuration updates only in
  `registering` and `available`, not `provisioned`.
- Ironic protects changes to `local_link_connection` outside enrollment,
  inspection, and manageable states unless maintenance is enabled.
  A separate, non-PXE third NIC does not bypass this restriction.

Maintenance was investigated, but no maintenance workaround was executed
or verified. It is not part of the recommended demo.

An available host uses idle-network configuration. The checked Ironic
implementation does not fall back to tenant port intent when idle
configuration is absent. Consequently, selecting tenant VLAN 3 while
`available` does not guarantee immediate VLAN 3 programming.

The intended tenant configuration is selected when the node is active.
Its application through our complete provisioning workflow remains
unverified.

Sources checked:

- [BMO state gate](https://github.com/metal3-io/baremetal-operator/blob/ed91ef80ce226a6bdd23b8794990d0008a07f0ee/pkg/provisioner/provisioner.go#L108)
- [Ironic protected port attributes](https://github.com/openstack/ironic/blob/24653cf01b0ddd1395ad6c244b23ed62627a067b/ironic/conductor/manager.py)
- [Ironic networking lifecycle resolution](https://github.com/openstack/ironic/blob/24653cf01b0ddd1395ad6c244b23ed62627a067b/ironic/drivers/modules/network/ironic_networking.py)

Recheck behavior when changing component versions.

## Original proposal and LLDP

[metal3-io/metal3-docs#586](https://github.com/metal3-io/metal3-docs/pull/586)
assumes inspection has populated switch-port mappings through LLDP and
recommends selecting attachments after inspection. Dynamic changes after
deployment are explicitly outside its scope.

Our late manual mapping differs from that assumed path. Users should not
need to know every NIC MAC before inspection to follow the discovery flow.

The installed Ironic configuration was checked read-only and has:

- Agent inspection enabled.
- `ipa-collect-lldp=1`.
- `parse-lldp` and `local-link-connection` inspection hooks enabled.
- `add_ports=all` and `keep_ports=present`.

Enabled hooks do not prove discovery works. We still need to verify LLDP
delivery to the third NIC and the resulting Ironic port mapping. The
checked mapping hook accepts a MAC-address chassis ID; advertised port
identifiers must also be usable by the chosen switch driver.

## OVS versus a virtual switch OS

OVS supports the access VLAN 3 commands used by the installed driver.
The SSH failure is not evidence that OVS cannot support the demo.
Stable libvirt tap names do not preserve VLAN configuration if ports are
recreated; verify the actual switch state after provisioning.

A virtual switch OS could advertise LLDP and provide recognizable switch
commands for the audience. Installed drivers include Arista EOS, Cumulus,
and SONiC. Driver presence does not prove compatibility with a particular
virtual image.

A virtual switch adds image acquisition, link wiring, LLDP, and management
access setup. It does not remove BMO's post-provision restriction or
Ironic's idle-network behavior.

Before committing to a rebuild, prove one host's inspection discovers a
correct mapping. Then test VLAN intent and provisioning. No virtual
switch image or end-to-end virtual-switch integration has been verified.

## SSH blocker: observations and unknowns

The switch is currently OVS on the host. Ironic's networking pod connects
to `172.18.0.1:22` as `root` using the mounted dedicated lab key.

The actual pod-side test failed before authentication:

```text
Exceeded MaxStartups
```

Observed facts:

- The SSH endpoint is reachable, but key authentication and remote OVS
  command execution remain unverified.
- Effective `MaxStartups` is `10:30:100`: rejection starts probabilistically
  at 10 pending unauthenticated connections and becomes complete at 100.
- One snapshot showed 27 accepted but unauthenticated SSH processes.
- SSH listens on all host interfaces; the IPv4 INPUT policy is ACCEPT.
- Incoming SSH SYNs were captured on uplink `enp0s5`, destined for
  `10.10.20.62:22`, with the upstream gateway's Ethernet source MAC.
- No host-side port-22 NAT rule was found in the inspected NAT table.
- The two libvirt guests attach to lab bridges, not directly to the uplink.
- The inspected local `nc` processes connect to guest console ports
  5900 and 5901, not port 22.

This establishes the ingress path, not the original traffic generator.
We have not proved internet scanning, excluded upstream infrastructure
testing, or excluded a routed-out-and-back path. Public-looking source
addresses alone do not establish origin.

The dev-env [firewall role](../vm-setup/roles/firewall/tasks/iptables.yaml)
stops firewalld. Whether that removed previously effective isolation is
unknown.

Do not blanket-block SSH or the gateway MAC: administrator public-IP
access may use the same listener and gateway. Before any filtering,
identify trusted administrator and Ironic sources, preserve existing
sessions, arrange rollback, and verify new administrator connections.
A separate private SSH listener was proposed but not created.

## Other findings

- [Bifrost CI](https://github.com/openstack/bifrost) demonstrates Ironic
  networking with OVS and initial mappings, but does not use BMO. It is
  not proof of this combined BMO workflow.
- The checked installed API requires a native VLAN for trunk attachments.
  The checked OVS trunk driver uses native-untagged behavior. Tagged-only
  operation was not demonstrated; access VLAN 3 is the chosen scope.
- Ubuntu provisioning hit an HTTP 403 for a checksum with incorrect file
  permissions. Quoting Ansible mode as `"0644"` fixed that issue. It was
  separate from switch networking.
- Local experimental BMO live-update changes remain untested and
  undeployed. They are not required or accepted evidence for this demo.

## Readiness and next verification

The target cluster was deleted through an approved deprovisioning step.
At the last checks, both BMHs were available, the VLAN intent existed in
their specs, applied attachment status was empty, and OVS tags were unset.
No subsequent reprovisioning or successful VLAN/connectivity test occurred.

Required evidence before calling the demo ready:

1. Networking pod authenticates with the actual mounted switch credential,
   verifies the host key, and executes read-only switch commands.
1. Inspection or initial registration establishes the correct third-NIC
   mappings before the hosts become available.
1. Selecting VLAN intent succeeds without an identity-changing PATCH.
1. Provisioning applies access VLAN 3 to the actual intended switch ports.
1. Both guests communicate over their third NICs with separately configured
   test IPs, without changes to provisioning or external networking.

Do not manually set VLAN tags to make the demonstration pass. BMO
validation, IrSO switch reconciliation, or applied status alone does not
prove switch programming. Teardown, firewall changes, SSH edits, and
provisioning require explicit operational approval.
