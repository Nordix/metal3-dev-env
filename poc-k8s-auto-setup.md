# BMC poc

## Configure repos and branches

* Clone metal3-dev-env

```sh
git clone https://github.com/Nordix/metal3-dev-env
cd metal3-dev-env
git checkout k8s_auto_setup_poc

```

* Export variables to config_example.sh

```sh
export CAPBMREPO="${CAPBMREPO:-https://github.com/Nordix/cluster-api-provider-baremetal.git}"
export CAPBMBRANCH="${CAPBMBRANCH:-k8s_auto_setup_poc}"
export CAPBM_RUN_LOCAL=true
export BMOBRANCH="${BMOBRANCH:-2d1cfeabcddb175fc3652c17045991a01f215876}"

```

* Create the nodes

```sh
cd metal3-dev-env
make

```

* Run the CAPBM locally to use local build

```sh
cd ~/go/src/github.com/metal3-io/cluster-api-provider-baremetal

# Kill the conroller
kill -9 $(pgrep -x main)

# Set the go env
eval $(go env)
export GOPATH

# Run the controller
make run
```

## Monitor progress

The following commands helps you monitor the progress of each component.

The machines need to be in running state

```sh
virsh list --all
```

* Create machine resources

```sh
./create_machine.sh worker
./create_machine.sh master
```

* Verify that cloudinit data is created as secret.

```sh
kubectl get secrets -n metal3 -o name
**master-user-data**
**worker-user-data**
```

* Check BMH status. Provisioning might take **>10**

```sh
watch kubectl get bmh -n metal3
```

* SSH to the machines
PS: BMH are randomly choosen as master, worker

```sh
ssh centos@192.168.111.21
ssh centos@192.168.111.20
```

* Check the logs

```sh
tailf /var/log/cloud-init-output.log
```

* Check from master node after ssh

```sh
kubectl get nodes
```

* Check if cluster is ready from host machine

```sh
curl -k https://192.168.111.249:6443/healthz
```

### Restart the process

* Re-provision the host and cluster

```sh
# delete cloud machine resources
kubectl delete machines -n metal3 master worker
# Delete cloud init data
kubectl delete secrets -n metal3 master-user-data worker-user-data
# De-provision nodes
./deprovision_host.sh worker-0
./deprovision_host.sh master-0
```

* Create resources

```sh
# create cloud init data
cd ~/metal3-dev-env
./user_data.sh

# verifty cloud init data creation
ls ~/*-user-data.yaml

# creat machines in any order
./create_machine.sh worker
./create_machine.sh master
```
