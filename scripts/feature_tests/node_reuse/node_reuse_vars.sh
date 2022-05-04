#!/bin/bash

export UPGRADED_K8S_VERSION="v1.24.0"

if [[ "${IMAGE_OS}" == "ubuntu" ]]; then
  export UPGRADED_IMAGE_NAME="UBUNTU_20.04_NODE_IMAGE_K8S_${UPGRADED_K8S_VERSION}.qcow2"
  export UPGRADED_RAW_IMAGE_NAME="UBUNTU_20.04_NODE_IMAGE_K8S_${UPGRADED_K8S_VERSION}-raw.img"
else
  export UPGRADED_IMAGE_NAME="CENTOS_8_NODE_IMAGE_K8S_${UPGRADED_K8S_VERSION}.qcow2"
  export UPGRADED_RAW_IMAGE_NAME="CENTOS_8_NODE_IMAGE_K8S_${UPGRADED_K8S_VERSION}-raw.img"
fi
