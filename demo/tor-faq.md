# ToR networking demo: architecture and Q&A

Read this before presenting the demo. It explains how the pieces fit
together and answers the common follow-up questions. For the step-by-step
guide see [the demo guide](tor-networking.md). For the investigation
record and fixes see [the lessons learned](tor-lessons-learned.md).

## What the demo shows

A user declares, in Kubernetes, which VLAN a host's workload NIC must use.
Metal3 configures the switch port to match, before the workload runs. No
one logs in to the switch by hand.

```text
BareMetalSwitch + HostNetworkAttachment + BMH networkInterfaces
    -> BMO -> Ironic -> networking-generic-switch -> the switch
```

The demo uses an OVS bridge as the switch and two dev-env guests, each
with a third NIC. The switch port gets access VLAN 3. The two guests then
reach each other over VLAN 3.

## The components

| Component | Role |
|-----------|------|
| BMO (Baremetal Operator) | Reconciles the BMH. Writes the switch intent and the port mapping to the Ironic port. |
| Ironic | Manages the host lifecycle. Its networking service programs the switch during port binding. |
| IrSO (Ironic Standalone Operator) | Deploys and configures Ironic and the `ironic-networking` service. Mounts the switch config and credentials. |
| networking-generic-switch (NGS) | A Python library of per-vendor drivers. Turns "set port to VLAN X" into the vendor's commands. |
| Netmiko | The SSH/CLI library most NGS drivers use to send the commands. |

### Is networking-generic-switch a service?

No. It is a Python **library/plugin** (`networking_generic_switch`). It
holds the device driver classes and the transport glue. In full OpenStack
it is a Neutron ML2 mechanism driver. In this demo there is no Neutron:
Ironic's own networking service loads NGS directly as a library.

### How does Ironic use NGS?

1. IrSO writes the switch config. Ironic translates it to a
   `genericswitch:<switch>` section in `switches.conf`.
1. NGS reads that config and creates one device object per switch, using
   `device_type`, `address`, `username`, and `key_file`.
1. When a port binds (the node becomes active during provisioning), Ironic
   calls the device. NGS formats the commands and sends them over SSH.
1. When the port unbinds (deprovision), NGS clears them.

The conductor talks to the networking service over json-rpc with TLS. That
TLS link is the one that needed a fix (see below).

## The custom resources and who sets them

| Resource | What it defines | Who creates it | Auto-discoverable |
|----------|-----------------|----------------|-------------------|
| `BareMetalSwitch` | The switch: address, MAC, `deviceType`, credentials | Operator, once | No |
| `HostNetworkAttachment` (HNA) | The VLAN intent: mode and VLAN IDs | Operator, once | No |
| BMH `networkInterfaces[]` | Binds a NIC to an HNA and a switch port | Operator, per BMH | No for the HNA; the `switchPort` part can come from LLDP |
| Secret (switch credentials) | Username and SSH key for the switch | Operator, once | No |

A BMH entry looks like this:

```yaml
spec:
  networkInterfaces:
    - macAddress: DEMO_NIC_MAC
      hostNetworkAttachment:
        name: tenant-vlan3        # the VLAN intent; always operator-set
      switchPort:                 # the mapping; LLDP replaces this
        switchID: "00:00:5e:00:53:01"
        portID: tor-port-0
```

## deviceType values

`deviceType` selects the NGS driver. It is a free-form string that must
match an installed NGS device type. The installed set includes:

```text
netmiko_ovs_linux   netmiko_arista_eos   netmiko_cisco_ios
netmiko_cisco_nxos  netmiko_cisco_s300   netmiko_juniper
netmiko_dell_force10 netmiko_dell_os10   netmiko_dell_powerconnect
netmiko_dell_enterprise_sonic           netmiko_sonic
netmiko_cumulus     netmiko_cumulus_nvue netmiko_nokia_srl
netmiko_aruba_aoscx netmiko_hp_comware   netmiko_hpe_comware
netmiko_huawei      netmiko_huawei_vrpv8 netmiko_mellanox_mlnxos
netmiko_brocade_fastiron netmiko_pluribus netmiko_ruijie
netmiko_supermicro_smis  netmiko_fake    netconf_openconfig
```

The demo uses `netmiko_ovs_linux`. `netmiko_fake` is a no-op test device.
`netconf_openconfig` uses NETCONF and OpenConfig models instead of CLI.

### Does this cover most industry switches?

Yes, for data-center and enterprise top-of-rack switching. It covers the
major vendors (Cisco, Arista, Juniper, Dell, HPE/Aruba, Huawei, Nokia,
NVIDIA/Mellanox) and the open NOSes (SONiC, Cumulus), with NETCONF and
OpenConfig as a vendor-neutral fallback. Caveats:

- The drivers are mostly CLI (Netmiko). A specific firmware version may
  still need validation. A driver is not a guarantee.
- The scope is switch-port VLAN and trunk configuration, not full switch
  management.
- NGS is extensible: you can add a device by subclassing.

## NETCONF and OpenConfig

NGS has two driver families. Most drivers are Netmiko and drive the CLI
over SSH. One driver, `netconf_openconfig`, uses NETCONF instead.

NETCONF (RFC 6241) is a network management protocol. It runs over SSH,
usually on port 830. It exchanges XML-encoded RPCs and operates on
structured configuration datastores, such as running and candidate. It
supports transactions: write to the candidate datastore, commit, and roll
back on error. It carries data modeled in YANG.

OpenConfig is a set of vendor-neutral YANG data models. Network operators
started it so that one model configures many vendors the same way. The
`netconf_openconfig` driver sends OpenConfig-modeled config over NETCONF
with the `ncclient` library.

How it differs from the Netmiko drivers:

| Aspect | Netmiko (CLI) | NETCONF and OpenConfig |
|--------|---------------|------------------------|
| Transport | SSH to the CLI | NETCONF over SSH (port 830) |
| Encoding | Plain-text commands | XML-encoded RPCs, YANG data |
| Per vendor | One command template per driver | One vendor-neutral model |
| Safety | Send text, parse text | Candidate datastore, commit, rollback |
| Robustness | Sensitive to prompts and firmware | Structured, less brittle |
| Requirement | SSH CLI access | NETCONF plus the OpenConfig models |

When to prefer NETCONF and OpenConfig:

- The device supports NETCONF and the OpenConfig models.
- You want vendor-neutral config and transactional safety (commit and
  rollback).

Caveats:

- OpenConfig support varies by vendor, platform, and version. Some devices
  implement only native YANG models, not OpenConfig.
- The demo uses the Netmiko OVS driver, not NETCONF. OVS has no NETCONF
  interface.

## HostNetworkAttachment modes

`spec.mode` is one of `access`, `trunk`, or `hybrid`.

| Mode | Behavior | Fields | OVS commands |
|------|----------|--------|--------------|
| `access` | Untagged single VLAN. The switch tags the guest's untagged traffic. | `nativeVLAN` | `vlan_mode=access`, `tag=<nativeVLAN>` |
| `trunk` | Tagged VLANs on the wire. The guest must tag. Still has a native VLAN. | `nativeVLAN`, `allowedVLANs` | `vlan_mode=native-untagged`, `tag=<native>`, `trunks=<allowed>` |
| `hybrid` | Access plus trunk on one port: one untagged VLAN and tagged VLANs. | `nativeVLAN`, `allowedVLANs` | same as trunk |

Notes:

- `nativeVLAN` is required for all modes. Tagged-only is not supported by
  the installed driver.
- For a tagged VLAN, the guest needs a VLAN subinterface (for example
  `enp3s0.10`). For access VLAN 3, the guest needs no VLAN config.

## LLDP versus the manual switchPort

The `switchPort` block is a stand-in for LLDP.

- In a real switch with LLDP, inspection discovers the mapping. The IPA
  ramdisk collects LLDP, and inspection hooks write the Ironic port's
  `local_link_connection` (switch ID and port ID) automatically. You omit
  `switchPort`.
- Our switch is OVS, which does not advertise LLDP to these ports. So the
  Ironic ports had no mapping, and we supply `switchPort` by hand.

Important: LLDP only auto-populates the **mapping**. The VLAN **intent**
(the `hostNetworkAttachment` reference) is always operator-declared. A
switch can say where a NIC is plugged in; it cannot say which VLAN you
want.

For LLDP discovery to work, the switch must enable LLDP, and the
advertised port ID must be the identifier the driver uses to configure the
port.

## When is the switch actually programmed?

There are two separate moments.

1. **Declaring the intent.** BMO writes the intent to the Ironic port. BMO
   allows this only while the BMH is `registering` or `available`, not
   `provisioned`. So declare the intent before provisioning.
1. **Applying it to the switch.** NGS runs the real commands during the
   bind and unbind steps: at **provisioning** (plug) and at
   **deprovisioning** (unplug). While the host sits idle in `available`,
   the intent is recorded but no command runs.

So the actual switch configuration happens during the provisioning and
deprovisioning transitions, not while the node is idle.

### Can maintenance mode change the VLAN on a provisioned host?

No. BMO's gate is keyed only on the provisioning state, with no
maintenance check:

```go
func CanUpdateSwitchPortConfig(state metal3api.ProvisioningState) bool {
    switch state {
    case metal3api.StateRegistering, metal3api.StateAvailable:
        return true
    default:
        return false
    }
}
```

A `provisioned` host returns `false`, so BMO never sends the update,
maintenance on or off. Maintenance relaxes a different, lower Ironic gate,
but that path is never reached here, and nothing re-binds the port while
provisioned. To change the VLAN of a provisioned node, deprovision it,
change the intent while `available`, then reprovision.

## Persistence with OVS

The first runs lost the VLAN after the guest rebooted. The switch port was
the libvirt-managed OVS port. libvirt removed and re-added the port on each
power cycle, and the new port had no VLAN.

The fix makes the OVS ports host-owned and persistent. vm-setup creates
each port as a tap and attaches the guest demo NIC with libvirt
`managed='no'`, so libvirt never deletes the port. A systemd service
recreates the ports on host boot. Metal3 programs the VLAN once, and it
survives guest power cycles. This is verified: the VLAN held across deploy
reboots and a hard power cycle, and the guests pinged over VLAN 3.

## The TLS fix

When the demo is enabled, the conductor connects to the
`ironic-networking` service by its Kubernetes DNS name with TLS
verification on. The generated Ironic certificate had only an IP SAN and
was reused as its own CA file. Verification failed, cleaning looped in
`clean failed`, and no port was programmed.

The dev-env now adds the service DNS name to the certificate SAN and
bundles the CA, so verification passes. This path exists only when the
demo is enabled, which is why normal dev-env runs never hit it.

## Quick verification commands

`ovs-vsctl` needs OVSDB access. Use `sudo`, or a shell that is in the
`ovsdb` group.

```bash
# Switch overview and ports
sudo ovs-vsctl show
sudo ovs-vsctl list-ports tor-switch

# The VLAN config per port (the deliverable)
for p in tor-port-0 tor-port-1; do
  echo "$p: mode=$(sudo ovs-vsctl get Port $p vlan_mode) \
tag=$(sudo ovs-vsctl get Port $p tag)"
done
# Expected: mode=access tag=3

# Which guest NIC each port maps to
sudo virsh -c qemu:///system domiflist node_0
```

```bash
# Metal3 side
export KUBECONFIG=/root/.kube/config    # or your kubeconfig
kubectl -n baremetal-operator-system get baremetalswitch
kubectl -n metal3 get hostnetworkattachment
kubectl -n metal3 get bmh \
  -o custom-columns=NAME:.metadata.name,STATE:.status.provisioning.state
```

## Known limitations and honest caveats

- The VLAN is applied at bind time, during provisioning. You cannot change
  it live on a provisioned host with this BMO and Ironic.
- CLI drivers depend on firmware behavior. Validate a specific NOS.
- OVS does not advertise LLDP here, so the mapping is manual. A real switch
  or a virtual switch appliance would advertise LLDP.
- A virtual switch appliance (Arista cEOS, SONiC, Cumulus) is an optional
  future improvement. It adds LLDP and a real CLI, at the cost of image and
  wiring setup. It does not change the Metal3 control path.
