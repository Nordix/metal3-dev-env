#!/bin/bash
set -xe

METAL3_DIR="$(dirname "$(readlink -f "${0}")")/.."

# shellcheck disable=SC1090,SC1091
source "${METAL3_DIR}/lib/common.sh"

# create ironic nodes 

## there should be a file that used to create fake vm on sushytools and from it we get ironic nodes
## the user just give the scalability number then the file generated automatically 


## understand the process for libvirt and use what can be used for fake ipa

### Generate nodes

#### in the very beginning we have num_nodes