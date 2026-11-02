# ToR switch configuration with Metal3: 8-minute talk

A speaker script for an 8-minute demo talk. It explains the feature,
shows the custom resources, and runs a short live demo. For the
step-by-step guide see [the demo guide](tor-networking.md). For follow-up
questions see [the Q&A](tor-faq.md).

## Before the talk: staging (important)

Provisioning takes about 10 minutes, so pre-provision before the talk so
that VLAN 3 is already programmed. During the 8 minutes you show the
result; you do not wait for it. Have ready:

- Two terminals: one for `kubectl`, one for `ovs-vsctl` and guest SSH.
- The three manifests on a slide: `BareMetalSwitch`,
  `HostNetworkAttachment`, and the BMH `networkInterfaces` snippet.
- A simple switch diagram.
- A working ping in a spare terminal as a backup.

Do not attempt a live VLAN change on a provisioned host. That needs
deprovision and reprovision, which is too slow and is not supported live.

## 0:00-1:00 The problem

Slide: a top-of-rack switch with two servers cabled to it, one port
highlighted.

> When we provision a bare-metal server, its workload NIC must land on the
> right VLAN. Today someone logs in to the top-of-rack switch and
> configures that port by hand, out of band from the Kubernetes workflow.
> Metal3 now lets us declare that in Kubernetes, and it configures the
> switch port for us, before the workload runs.

## 1:00-2:30 Define the switch: BareMetalSwitch

Slide: the switch diagram, with a `BareMetalSwitch` CR animating in from
the side.

> First we tell Kubernetes the switch exists.

```yaml
apiVersion: metal3.io/v1alpha1
kind: BareMetalSwitch
metadata:
  name: tor-switch
spec:
  address: <reachable-ip>
  macAddress: "00:00:5e:00:53:01"
  deviceType: netmiko_ovs_linux      # selects the driver
  credentials:
    name: tor-switch-creds
```

> It is the switch address, its identity, which driver to use, and a
> secret with the switch credentials. One of these per switch.

## 2:30-4:00 Declare the intent: HostNetworkAttachment and the BMH

Slide: the `HostNetworkAttachment` CR, then the BMH snippet.

> Next, the intent: what we want the connected port to be.

```yaml
apiVersion: metal3.io/v1alpha1
kind: HostNetworkAttachment
metadata:
  name: tenant-vlan3
spec:
  mode: access
  nativeVLAN: 3
```

> This is a reusable VLAN definition. Here it is access VLAN 3. Then we
> attach it to a specific NIC on the host.

```yaml
spec:
  networkInterfaces:
    - macAddress: <demo-nic-mac>
      hostNetworkAttachment:
        name: tenant-vlan3
```

> In production, with LLDP, that is all we write. Inspection discovers the
> switch-port mapping automatically. In this lab the switch is OVS with no
> LLDP, so we add a `switchPort` by hand. Either way we only declare
> intent. We never touch the switch.

## 4:00-5:00 Under the hood

Slide: the chain diagram.

```text
BMH + HNA -> BMO -> Ironic -> networking-generic-switch -> the switch
                                     |
                       Netmiko (SSH/CLI)  or  NETCONF (OpenConfig)
```

> BMO records the intent on the Ironic port. At provisioning, Ironic's
> networking service calls networking-generic-switch, an OpenStack library
> of per-vendor drivers. Most drivers use Netmiko to send CLI over SSH;
> one uses NETCONF with OpenConfig. That is what gives us broad vendor
> coverage: Cisco, Arista, Juniper, Dell, SONiC, Cumulus, and OVS for this
> demo.

## 5:00-7:30 The demo

Terminal 1, the declared state:

```bash
kubectl get baremetalswitch
kubectl -n metal3 get hostnetworkattachment
kubectl -n metal3 get bmh
```

Terminal 2, the switch was actually programmed:

```bash
sudo ovs-vsctl show
for p in tor-port-0 tor-port-1; do
  echo "$p: mode=$(sudo ovs-vsctl get Port $p vlan_mode) \
tag=$(sudo ovs-vsctl get Port $p tag)"
done
# Expected: mode=access tag=3 on both
```

> No one touched the switch. Metal3 set these ports to access VLAN 3.

The proof it works end to end, a same-VLAN ping:

```bash
# from guest 1 (10.30.0.11) to guest 2 (10.30.0.12)
ping -I enp3s0 -c 3 10.30.0.12
```

Optional, if time allows, the evidence in the log:

```bash
kubectl -n baremetal-operator-system logs deploy/ironic-networking \
  | grep "Successfully configured port"
```

## 7:30-8:00 Takeaways

> Declare the switch and the VLAN intent in Kubernetes. Metal3, through
> Ironic and networking-generic-switch, programs the real switch port,
> across many vendors. No manual switch config, fully declarative, and
> part of the provisioning flow.

## Delivery tips

- Pre-stage the demo. Do not provision live in an 8-minute slot.
- Do not demonstrate a live VLAN change on a provisioned host. It needs
  deprovision and reprovision, and it is not supported live.
- Keep the LLDP point to one sentence. The depth is in the Q&A.
- Keep a working ping in a spare terminal as a backup.

## Demo runbook (recorded)

The demo is recorded and edited. Run the steps in order. Cut the
provisioning wait in post: keep the commands and the CRD applies, cut the
10 to 15 minute wait, and keep the ping. The commands use this lab's names
(`tor-switch`, `tor-port-0`, `tor-port-1`) and the current demo NIC MACs.
Re-fetch the MACs after any redeploy.

### What to keep and what to cut

- Keep: applying the CRDs, the BMH patches, the before and after OVS
  output, and the ping.
- Cut: the provisioning wait. Jump from "provisioning started" to the
  programmed result.

### Prerequisites (once, before recording)

```bash
export KUBECONFIG=/home/ubuntu/.kube/config
KEY=/home/ubuntu/.copilot/session-state/1cf6925f-a884-4e02-803f-59475e94b0f2/files/labsw0_ovs_key

# switch credentials secret
kubectl -n baremetal-operator-system create secret generic tor-switch-creds \
  --from-literal=username=ubuntu \
  --from-file=ssh-privatekey="$KEY"

# both hosts should be available with no networkInterfaces yet
kubectl -n metal3 get bmh

# demo NIC MAC per node (re-run after any redeploy)
for n in node_0 node_1; do
  echo "$n: $(sudo virsh -c qemu:///system domiflist $n | awk '/tor-port/{print $5}')"
done
```

Current MACs in this lab: node-0 `00:62:02:f5:43:20` on `tor-port-0`,
node-1 `00:62:02:f5:43:23` on `tor-port-1`.

### Step 1: define the switch

```bash
kubectl apply -f - <<'EOF'
apiVersion: metal3.io/v1alpha1
kind: BareMetalSwitch
metadata:
  name: tor-switch
  namespace: baremetal-operator-system
spec:
  address: "172.18.0.1"           # host IP reachable from the pod; verify
  macAddress: "00:00:5e:00:53:01"
  deviceType: netmiko_ovs_linux
  credentials:
    name: tor-switch-creds
EOF
kubectl -n baremetal-operator-system get baremetalswitch tor-switch
# VALID should be True
```

### Step 2: declare the VLAN intent

```bash
kubectl apply -f - <<'EOF'
apiVersion: metal3.io/v1alpha1
kind: HostNetworkAttachment
metadata:
  name: tenant-vlan3
  namespace: metal3
spec:
  mode: access
  nativeVLAN: 3
EOF
```

### Step 3: bind the NICs on the BMHs (while available)

```bash
kubectl -n metal3 patch baremetalhost node-0 --type merge -p '{"spec":{"networkInterfaces":[{"macAddress":"00:62:02:f5:43:20","hostNetworkAttachment":{"name":"tenant-vlan3"},"switchPort":{"switchID":"00:00:5e:00:53:01","portID":"tor-port-0"}}]}}'
kubectl -n metal3 patch baremetalhost node-1 --type merge -p '{"spec":{"networkInterfaces":[{"macAddress":"00:62:02:f5:43:23","hostNetworkAttachment":{"name":"tenant-vlan3"},"switchPort":{"switchID":"00:00:5e:00:53:01","portID":"tor-port-1"}}]}}'

# BMO accepts the intent
kubectl -n metal3 get bmh node-0 \
  -o jsonpath='{.status.operationalStatus}{"\n"}'
```

### Step 4: show the switch BEFORE provisioning

```bash
for p in tor-port-0 tor-port-1; do
  echo "$p: tag=$(sudo ovs-vsctl get Port $p tag)"
done
# Expected: tag=[]  (intent recorded, not yet programmed)
```

### Step 5: start provisioning (cut the wait in post)

```bash
export IMAGE_OS=ubuntu
./tests/scripts/provision/cluster.sh
./tests/scripts/provision/controlplane.sh
./tests/scripts/provision/worker.sh
```

### Step 6: show the switch AFTER provisioning

```bash
for p in tor-port-0 tor-port-1; do
  echo "$p: mode=$(sudo ovs-vsctl get Port $p vlan_mode) \
tag=$(sudo ovs-vsctl get Port $p tag)"
done
# Expected: mode=access tag=3

kubectl -n baremetal-operator-system logs deploy/ironic-networking \
  | grep "Successfully configured port"
```

### Step 7: ping over VLAN 3

```bash
# SSH into each guest (external network), set the demo IPs on enp3s0:
#   node-0: 10.30.0.11/24
#   node-1: 10.30.0.12/24
# then from node-0:
ping -I enp3s0 -c 3 10.30.0.12
```

### Reset to a clean start (for re-recording)

```bash
kubectl -n metal3 delete cluster test1 --wait=false
# wait until both BMHs are available again, then clear the intent:
kubectl -n metal3 patch baremetalhost node-0 \
  --type merge -p '{"spec":{"networkInterfaces":[]}}'
kubectl -n metal3 patch baremetalhost node-1 \
  --type merge -p '{"spec":{"networkInterfaces":[]}}'
```

The switch, HNA, and credentials can stay between runs. Re-apply them only
if you want to show those steps again.

## Likely questions and where to find the answers

All answers are in [the Q&A](tor-faq.md):

- Which vendors are supported, and `deviceType` values.
- Netmiko versus NETCONF, and which is more common.
- When the switch is programmed, and why a live change needs
  reprovisioning.
- How LLDP auto-discovery replaces the manual `switchPort`.
- How the VLAN persists across guest reboots.
