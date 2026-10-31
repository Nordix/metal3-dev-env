#!/usr/bin/env bash

configure_kind_irso_network()
{
    local node_pid host_alias guest_alias host_index guest_peer
    : "${BARE_METAL_PROVISIONER_INTERFACE:?Provisioning interface must be configured}"
    : "${INITIAL_BARE_METAL_PROVISIONER_BRIDGE_IP:?Provisioning bootstrap address must be configured}"
    : "${BARE_METAL_PROVISIONER_CIDR:?Provisioning prefix must be configured}"
    node_pid=$(docker inspect --format '{{.State.Pid}}' kind-control-plane)
    if [[ ! "${node_pid}" =~ ^[0-9]+$ ]] || (( node_pid == 0 )); then
        echo "ERROR: kind-control-plane must be running to connect provisioning" >&2
        return 1
    fi
    sudo ip link show dev provisioning > /dev/null

    if [[ -e /sys/class/net/m3-kind-pro ]]; then
        host_alias=$(cat /sys/class/net/m3-kind-pro/ifalias)
        guest_alias=$(docker exec kind-control-plane cat \
            "/sys/class/net/${BARE_METAL_PROVISIONER_INTERFACE}/ifalias")
        host_index=$(cat /sys/class/net/m3-kind-pro/ifindex)
        guest_peer=$(docker exec kind-control-plane cat \
            "/sys/class/net/${BARE_METAL_PROVISIONER_INTERFACE}/iflink")
        if [[ "${host_alias}" != "metal3-dev-env:kind-irso" ||
              "${guest_alias}" != "metal3-dev-env:kind-irso" ||
              "${host_index}" != "${guest_peer}" ]]; then
            echo "ERROR: provisioning veth ownership or peer mismatch; refusing to reuse it" >&2
            return 1
        fi
    else
        if docker exec kind-control-plane ip link show dev "${BARE_METAL_PROVISIONER_INTERFACE}" > /dev/null 2>&1 ||
           sudo ip link show dev m3-kind-peer > /dev/null 2>&1; then
            echo "ERROR: provisioning veth interface name is already in use" >&2
            return 1
        fi
        sudo ip link add m3-kind-pro type veth peer name m3-kind-peer
        sudo ip link set dev m3-kind-pro alias metal3-dev-env:kind-irso
        sudo ip link set dev m3-kind-peer alias metal3-dev-env:kind-irso
        sudo ip link set dev m3-kind-peer netns "${node_pid}"
        docker exec kind-control-plane ip link set dev m3-kind-peer name "${BARE_METAL_PROVISIONER_INTERFACE}"
    fi

    sudo ip link set dev m3-kind-pro master provisioning
    sudo ip link set dev m3-kind-pro up
    docker exec kind-control-plane ip link set dev "${BARE_METAL_PROVISIONER_INTERFACE}" up
    # VRRP needs a base address on the interface before assigning its VIP.
    docker exec kind-control-plane ip address replace \
        "${INITIAL_BARE_METAL_PROVISIONER_BRIDGE_IP}/${BARE_METAL_PROVISIONER_CIDR}" \
        dev "${BARE_METAL_PROVISIONER_INTERFACE}"
}

remove_kind_irso_network()
{
    if [[ -e /sys/class/net/m3-kind-pro ]]; then
        if [[ "$(cat /sys/class/net/m3-kind-pro/ifalias)" != "metal3-dev-env:kind-irso" ]]; then
            echo "ERROR: refusing to remove unowned interface m3-kind-pro" >&2
            return 1
        fi
        sudo ip link delete dev m3-kind-pro
    fi
}
