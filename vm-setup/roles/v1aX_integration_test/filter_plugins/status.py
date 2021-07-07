""" filtering k8s_info resources """

from ansible.utils.display import Display

display = Display()


def msg(key, resources):
    return "could not find %r key in %r" % (key, resources)


def filter_phase(resources, phase):
    """Filter resources based on a defined phase

    Args:
        resources : Json object contains a list of k8s resources.
        phase (str): The status phase of the filtered resources
                    e.g. 'running', 'provisioning', 'deleting'.

    Returns:
        list: A list of resources in the defined phase.
    """

    filtered = []
    for r in resources:
        try:
            if r["status"]["phase"].lower() == phase:
                filtered.append(r)
        except KeyError:
            display.warning(msg("['status']['phase']", resources))

    return filtered


def filter_ready(resources):
    """return resources based on defined ready status"""
    filtered = []
    for r in resources:
        try:
            if r["status"]["ready"]:
                filtered.append(r)
        except KeyError:
            display.warning(msg("['status']['ready']", resources))

    return filtered


def filter_provisioning(resources, state):
    """Filter resources based on a defined provisioning state

    Args:
        resources : Json object contains a list of k8s resources.
        state (str): The provisioning state of the filtered resources
                    e.g. 'provisioned', 'ready', 'deprovisioning'.

    Returns:
        list: A list of resources in the defined provisioning state.
    """
    filtered = []
    for r in resources:
        try:
            if r["status"]["provisioning"]["state"].lower() == state:
                filtered.append(r)
        except KeyError:
            display.warning(msg("['status']['provisioning']['state']", resources))

    return filtered


def get_names(resources):
    """return resources names list"""
    names = []
    for r in resources:
        try:
            names.append(r["metadata"]["name"])
        except KeyError:
            display.warning(msg("['metadata']['name']", resources))

    return names


def filter_k8s_version(resources, version):
    """return resources with a defined k8s version"""
    filtered = []
    for r in resources:
        try:
            if r["spec"]["version"] == version:
                filtered.append(r)
        except KeyError:
            display.warning(msg("['spec']['version']", resources))

    return filtered


class FilterModule:
    def filters(self):
        filters = {
            "filter_phase": filter_phase,
            "filter_ready": filter_ready,
            "filter_provisioning": filter_provisioning,
            "get_names": get_names,
            "filter_k8s_version": filter_k8s_version,
        }
        return filters
