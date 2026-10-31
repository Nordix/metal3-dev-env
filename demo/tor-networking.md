# ToR networking demo

This workflow has not been verified end-to-end. Read the
[lessons learned](tor-lessons-learned.md) before running it: our late
mapping update was rejected, and switch SSH authentication remains
unverified. Correct port mappings must exist before hosts become available.

This live demo uses two normal dev-env guests, one OVS bridge (`labsw0`),
and a dedicated third NIC on each guest. BMO, Ironic, and
networking-generic-switch configure the VM-facing OVS ports.
Provisioning and external networking remain unchanged.

The use case is assigning a host's workload NIC to its intended switch
VLAN before provisioning, without configuring the switch manually.
BMO supplies the intent; Ironic and networking-generic-switch program
OVS. Guest IP configuration is separate.

## Lifecycle restriction

At upstream BMO commit `ed91ef80ce226a6bdd23b8794990d0008a07f0ee`,
[switch-port updates are allowed only for registering or available hosts](https://github.com/metal3-io/baremetal-operator/blob/ed91ef80ce226a6bdd23b8794990d0008a07f0ee/pkg/provisioner/provisioner.go#L108).
They are not applied after a host is provisioned. `IronicNetworking`
does not enable post-provision updates.

This guide demonstrates pre-provision access VLAN 3 configuration and
same-VLAN connectivity, not live VLAN changes. If the guests are already
provisioned, obtain separate approval for a deprovisioning/reprovisioning
procedure before following the configuration steps. Do not restart VM
setup or delete the target cluster as an implicit prerequisite.

```text
VM1 demo NIC                         VM2 demo NIC
10.30.0.11/24                         10.30.0.12/24
      |                                    |
      +-- access VLAN 3 -- labsw0 -- access VLAN 3
```

## Prepare the environment

Only run setup in a dedicated Metal3 development VM. These instructions
modify networking and create guests. Use a fresh environment: re-running
VM setup regenerates NIC MACs and is not a supported retrofit procedure.

Add these settings to your dev-env configuration before setup:

```bash
export USE_IRSO=true
export NUM_NODES=2
export ENABLE_TOR_DEMO=true
# Optional other gates are preserved:
# export BMO_FEATURE_GATES=HostClaims=true
```

Use main-branch BMO, IrSO, and Ironic images. Kind and minikube are supported
by the demo configuration; the Tilt deployment path is not wired for it.
Follow the normal [dev-env setup](../README.md), but leave the BMHs
`available` after inspection. Configure and verify switch intent before
running the target-cluster provisioning scripts.

Enabling the flag:

1. Adds the `tor-demo` libvirt network and third NIC to every bare-metal VM.
1. Installs OVS and creates `labsw0`, with a dev-env ownership marker.
   Setup refuses to adopt an existing unmarked bridge with that name.
1. Names the demo taps `m3tor0`, `m3tor1`, etc., in VM inventory order.
   Libvirt recreates these tap names when guests start.
1. Enables BMO's `IronicNetworking` gate, switch Secret configuration, and
   `ironic-networking` interface, including for locally run BMO.
1. Enables the networking service in the generated `Ironic` CR.

The bridge has no IP, DHCP, NAT, uplink, or manually configured VM port
VLANs. A stable tap name does not itself persist a VLAN after the tap is
recreated: verify reconciliation and connectivity after guest restarts.

For kind with IrSO, setup also connects the host's Linux `provisioning`
bridge to the kind control-plane container using a dedicated veth pair.
The host end is `m3-kind-pro`; the container end uses
`BARE_METAL_PROVISIONER_INTERFACE` (default `ironicendpoint`). This makes
the provisioning network visible to Ironic's host-networked pod inside
kind. Setup assigns the existing dev-env bootstrap address (normally
`172.22.0.9/24`) so VRRP has a base address. Keepalived assigns the Ironic
VIP (`172.22.0.2`); setup does not assign the VIP itself.
This connection is separate from `labsw0` and the
existing host-side `ironicendpoint`. Cluster cleanup removes the owned
veth pair. Recreate the connection after replacing/restarting the kind
container if its network namespace is replaced.

Inspect the actual mapping rather than assuming a VM name or NIC name:

```bash
sudo virsh -c qemu:///system list --all
sudo virsh -c qemu:///system domiflist node_0
sudo virsh -c qemu:///system domiflist node_1
sudo ovs-vsctl show
kubectl get baremetalhosts -A
```

Guests must have completed inspection after their third NIC was added.
Record each BMH name, namespace, demo NIC MAC, and `m3torN` port name.
Taps exist only while the guest is running.

## Allow switch management over SSH

Use a host IP reachable from the networking pod, not an address on
`labsw0`. Configure a dedicated lab SSH key and an account that can execute
`ovs-vsctl` directly with OVSDB access. The driver invokes `ovs-vsctl`;
granting access only to `sudo ovs-vsctl` is not sufficient unless the
driver is configured to invoke it that way.

For an isolated lab, an explicitly authorized root SSH key is an option;
do not enable password authentication or expose the account outside the
lab. Restrict key access to the lab and remove the authorization afterward.
Never make the OVSDB socket world-writable. Verify SSH host fingerprints
through a trusted channel before accepting them.

Verify the account can run `ovs-vsctl show` over SSH, then verify the same
reachability and authentication from the `ironic-networking` deployment
using the configured key. Do not copy private keys into logs, the source
tree, or a committed manifest.

## Declare the switch and VLAN intent

The following examples use the default Ironic namespace. Substitute your
configured `IRONIC_NAMESPACE` if different. IrSO creates
`ironic-switch-config` and `ironic-switch-credentials`; BMO fills them.
Create only the input switch credentials Secret yourself:

```bash
kubectl -n baremetal-operator-system create secret generic labsw0-creds \
  --from-literal=username=YOUR_LAB_SSH_USER \
  --from-file=ssh-privatekey=/absolute/path/to/lab-private-key
```

Apply the following resources, replacing `HOST_IP_REACHABLE_FROM_POD`.
The switch MAC is a manually chosen identity shared by the switch resource
and BMH mappings; this demo does not depend on LLDP.

```yaml
apiVersion: metal3.io/v1alpha1
kind: BareMetalSwitch
metadata:
  name: labsw0
  namespace: baremetal-operator-system
spec:
  address: HOST_IP_REACHABLE_FROM_POD
  macAddress: "00:00:5e:00:53:01"
  deviceType: netmiko_ovs_linux
  credentials:
    name: labsw0-creds
---
apiVersion: metal3.io/v1alpha1
kind: HostNetworkAttachment
metadata:
  name: tenant-vlan3
  namespace: baremetal-operator-system
spec:
  mode: access
  nativeVLAN: 3
```

Create HNAs in each BMH's namespace if it differs from the example.
Switch credentials must be in the switch's namespace. The two output
Secrets remain in the configured Ironic namespace.

While each BMH is `available`, add this entry to `spec.networkInterfaces`,
using its own demo MAC and tap name. Preserve any existing entries and all
other BMH fields; do not replace the entire BMH with this fragment:

```yaml
spec:
  networkInterfaces:
    - macAddress: DEMO_NIC_MAC
      hostNetworkAttachment:
        name: tenant-vlan3
      switchPort:
        switchID: "00:00:5e:00:53:01"
        portID: m3tor0
```

Wait for switch validation, BMH `NetworkInterfacesValid=True`, and matching
`status.appliedNetworkAttachmentConfigs`. Inspect the Ironic ports for
`extra.switchport` and `local_link_connection`, and verify both OVS tags:

```bash
sudo ovs-vsctl get Port m3tor0 tag
sudo ovs-vsctl get Port m3tor1 tag
```

Record the tags at this stage; they need not show `3` while the hosts use
idle-network configuration. The existing Ironic mappings must match the
desired switch identities without an identity-changing PATCH. Stop if
that prerequisite or the intent update fails.
Validation and applied status alone do not prove switch programming.

## Provision the guests

Only after the checks above succeed, follow the normal target-cluster
provisioning workflow. For Ubuntu, explicitly select the OS in the shell:

```bash
export IMAGE_OS=ubuntu
./tests/scripts/provision/cluster.sh
./tests/scripts/provision/controlplane.sh
./tests/scripts/provision/worker.sh
```

Wait for the guests to boot and Kubernetes bootstrap to complete. Verify
the actual OVS tags again before testing connectivity: both must show `3`
after tenant configuration is applied. Do not manually set tags to make
the test pass. Libvirt may
recreate taps during provisioning; stable names do not preserve VLAN
configuration. If the tags are lost, report the lifecycle failure rather
than manually restoring them or assuming provisioned-host reconciliation.

## Configure guest addresses

An `available` BMH alone cannot run ping: both guests need running operating
systems. Access them through the existing external network or console.
Identify the demo interface by the MAC recorded above, not by assuming
that it is named `eth2`.

First verify `10.30.0.0/24` does not overlap existing routes. Configure
persistent static addresses through each guest OS's network manager,
without DHCP, gateway, DNS, or a VLAN subinterface on the demo NIC:

| Guest | Demo address |
|-------|--------------|
| VM1 | `10.30.0.11/24` |
| VM2 | `10.30.0.12/24` |

For NetworkManager guests, use a dedicated connection matched to the demo
NIC MAC. Run inside VM1, substituting the recorded interface and MAC:

```bash
sudo nmcli connection add type ethernet con-name tor-demo ifname DEMO_IF \
  802-3-ethernet.mac-address DEMO_MAC \
  ipv4.method manual ipv4.addresses 10.30.0.11/24 \
  ipv4.never-default yes ipv6.method disabled
sudo nmcli connection up tor-demo
```

For Ubuntu guests using Netplan, add a separate
`/etc/netplan/90-tor-demo.yaml` with root-only permissions:

```yaml
network:
  version: 2
  ethernets:
    tor-demo:
      match:
        macaddress: "DEMO_MAC"
      dhcp4: false
      dhcp6: false
      accept-ra: false
      addresses:
        - 10.30.0.11/24
```

Apply with `sudo netplan try` from a console so unintended changes can be
rolled back. For Flatcar/systemd-networkd guests, create
`/etc/systemd/network/10-tor-demo.network`:

```ini
[Match]
MACAddress=DEMO_MAC

[Network]
Address=10.30.0.11/24
DHCP=no
IPv6AcceptRA=no
LinkLocalAddressing=no
```

Run `sudo networkctl reload` and `sudo networkctl reconfigure DEMO_IF`.
In all cases, use VM2's MAC and `10.30.0.12/24` for VM2. Inspect existing
guest profiles first and ensure only one profile manages the demo NIC.

For a temporary, non-persistent smoke test only, run inside each guest:

```bash
# VM1; replace DEMO_IF with the interface matched by MAC.
sudo ip link set dev DEMO_IF up
sudo ip address add 10.30.0.11/24 dev DEMO_IF
# VM2: use 10.30.0.12/24 instead.
```

Do not flush existing addresses or change default routes. Allow ICMP on
the demo interface using the guest firewall's normal configuration; do
not disable the firewall globally.

## Demonstrate same-VLAN connectivity

From VM1, with `DEMO_IF` replaced by the demo interface:

```bash
ip route get 10.30.0.12
ping -I DEMO_IF -c 3 -W 2 10.30.0.12
```

Verify the route uses that interface and `10.30.0.11` as its source.
Repeat in reverse from VM2 to `10.30.0.11`.

Record the BMO intent, Ironic port identity/configuration, actual OVS tags,
guest routes, and successful pings as the demo evidence. Both OVS port
tags must remain `3`, and provisioning/external networking must be
unchanged.

Do not demonstrate a VLAN 3-to-4 change on a provisioned BMH as though
upstream BMO supports live updates. Guest restart recovery is also not
an acceptance claim: tap recreation can lose VLAN state, and the
verified BMO state gate does not reapply it while the host is provisioned.

## Cleanup

1. Coordinate any host deprovisioning through a separately approved
   normal dev-env lifecycle. Do not deprovision implicitly for cleanup.
1. Remove only the demo entries from each BMH's `spec.networkInterfaces`
   when switch updates are permitted, then verify actual switch-port
   cleanup. Removing intent while provisioned does not prove cleanup.
1. Delete the HNA, `labsw0` switch resource, and `labsw0-creds` input
   Secret from their namespaces after references have been removed.
1. Remove the demo guest addresses/network profiles and SSH key
   authorization if retaining the guests.
1. For full teardown, keep `ENABLE_TOR_DEMO=true` while running normal
   dev-env cleanup in the dedicated lab VM. It removes the guests and
   libvirt networks, then the owned OVS bridge.

Cleanup refuses to remove an unmarked `labsw0`. It does not uninstall OVS,
delete unrelated bridges, or alter unrelated SSH accounts/keys. Keep the
flag enabled until cleanup has completed.

## Static validation

These checks do not provision hosts:

```bash
make lint
python3 -m unittest discover -s hack -p 'test_tor_demo.py'
python3 -m unittest discover -s hack -p 'test_kind_network.py'
```

The Python checks require Jinja2 and PyYAML, also used by Ansible.
Pre-provision switch programming, VLAN retention through provisioning,
same-VLAN ping, and cleanup require separate live checks on the dedicated
lab VM. Static tests do not prove those results.
