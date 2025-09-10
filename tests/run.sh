#!/usr/bin/env bash

set -eux

METAL3_DIR="$(dirname "$(readlink -f "${0}")")/.."

ACTION="${ACTION:-""}"

# shellcheck disable=SC1090,SC1091
source "${METAL3_DIR}/lib/logging.sh"
# shellcheck disable=SC1090,SC1091
source "${METAL3_DIR}/lib/common.sh"
# shellcheck disable=SC1090,SC1091
source "${METAL3_DIR}/lib/releases.sh"
# shellcheck disable=SC1090,SC1091
source "${METAL3_DIR}/lib/network.sh"
# shellcheck disable=SC1090,SC1091
source "${METAL3_DIR}/lib/images.sh"
# shellcheck disable=SC1090,SC1091
source "${METAL3_DIR}/lib/ironic_tls_setup.sh"
# shellcheck disable=SC1090,SC1091
source "${METAL3_DIR}/lib/ironic_basic_auth.sh"

if [[ -r "${CI_CONFIG_FILE}" ]]; then
   # shellcheck disable=SC1090,SC1091
   . "${CI_CONFIG_FILE}"
fi

# Disable SSH strong authentication
export ANSIBLE_HOST_KEY_CHECKING=False

# Ansible config file
export ANSIBLE_CONFIG=${METAL3_DIR}/ansible.cfg

# shellcheck disable=SC2086
ANSIBLE_FORCE_COLOR=true "${ANSIBLE}-playbook" \
    -e "metal3_dir=${SCRIPTDIR}" \
    -e "v1aX_integration_test_action=${ACTION}" \
    -i "${METAL3_DIR}/tests/inventory.ini" \
    -b -v "${METAL3_DIR}/tests/main.yml"
