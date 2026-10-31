"""Static ToR demo checks. Never source common.sh or run host setup."""

import ipaddress
import os
from pathlib import Path
import re
import subprocess
import tempfile
import unittest
import xml.etree.ElementTree as ET

import jinja2
import yaml


ROOT = Path(__file__).resolve().parents[1]
ROLES = ROOT / "vm-setup/roles"


def load_yaml(path):
    return yaml.safe_load(path.read_text())


def template_environment():
    environment = jinja2.Environment(undefined=jinja2.ChainableUndefined)
    environment.filters["bool"] = lambda value: str(value).lower() == "true"
    environment.filters["ansible.utils.ipmath"] = (
        lambda value, offset: str(ipaddress.ip_address(value) + int(offset))
    )
    environment.filters["regex_search"] = lambda value, pattern: re.search(pattern, value)
    return environment


class TorDemoTests(unittest.TestCase):
    def settings(self, **overrides):
        source = (ROOT / "lib/common.sh").read_text()
        start = source.index('if [[ "${ENABLE_TOR_DEMO}" != "true"')
        end = source.index("# Kubectl version", start)
        environment = dict(
            PATH=os.environ["PATH"],
            ENABLE_TOR_DEMO="false",
            USE_IRSO="true",
            NODES_PLATFORM="libvirt",
            BOOTSTRAP_CLUSTER="kind",
            NUM_NODES="2",
            BMO_FEATURE_GATES="",
        )
        for key in ("FEATURE_GATES", "IRONIC_SWITCH_CONFIGS_SECRET",
                    "IRONIC_SWITCH_CREDENTIALS_SECRET",
                    "IRONIC_SWITCH_CREDENTIALS_PATH", "IRONIC_NETWORK_INTERFACE"):
            environment.pop(key, None)
        environment.update(overrides)
        return subprocess.run(
            ["bash", "-eu", "-c", source[start:end] + "\nenv"],
            env=environment, capture_output=True, text=True, check=False,
        )

    def test_disabled_settings(self):
        result = self.settings()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertNotIn("\nFEATURE_GATES=", result.stdout)
        self.assertNotIn("IRONIC_SWITCH_CONFIGS_SECRET=", result.stdout)

    def test_gate_merging_and_local_environment(self):
        for gates in ("", "HostClaims=true", "IronicNetworking=true"):
            with self.subTest(gates=gates):
                result = self.settings(
                    ENABLE_TOR_DEMO="true", BMO_FEATURE_GATES=gates,
                )
                self.assertEqual(result.returncode, 0, result.stderr)
                environment = dict(line.split("=", 1)
                                   for line in result.stdout.splitlines())
                enabled = environment["FEATURE_GATES"].split(",")
                self.assertEqual(enabled.count("IronicNetworking=true"), 1)
                if gates == "HostClaims=true":
                    self.assertIn(gates, enabled)
                self.assertEqual(environment["IRONIC_NETWORK_INTERFACE"],
                                 "ironic-networking")
                self.assertEqual(environment["IRONIC_SWITCH_CONFIGS_SECRET"],
                                 "ironic-switch-config")

    def test_generic_feature_gates_without_demo(self):
        result = self.settings(BMO_FEATURE_GATES="HostClaims=true")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("FEATURE_GATES=HostClaims=true\n", result.stdout)

    def test_invalid_settings_fail_explicitly(self):
        cases = [
            {"ENABLE_TOR_DEMO": "yes"},
            {"USE_IRSO": "false"},
            {"NODES_PLATFORM": "fake"},
            {"BOOTSTRAP_CLUSTER": "tilt"},
            {"BOOTSTRAP_CLUSTER": "invalid"},
            {"NUM_NODES": "1"},
            {"NUM_NODES": "invalid"},
            {"BMO_FEATURE_GATES": "HostClaims=true,IronicNetworking=false"},
        ]
        for case in cases:
            with self.subTest(case=case):
                settings = {"ENABLE_TOR_DEMO": "true", **case}
                result = self.settings(**settings)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("ERROR:", result.stderr)

    def test_vm_interfaces_and_demo_network(self):
        environment = template_environment()
        common = load_yaml(ROLES / "common/defaults/main.yml")
        defaults = load_yaml(ROLES / "libvirt/defaults/main.yml")
        nodes = [{"name": "node_0", "flavor": "node"},
                 {"name": "node_1", "flavor": "node"}]
        base_networks = [
            {"name": "provisioning", "bridge": "provisioning"},
            {"name": "external", "bridge": "external"},
        ]
        vm_template = environment.from_string(
            (ROLES / "libvirt/templates/baremetalvm.xml.j2").read_text()
        )
        for enabled in (False, True):
            networks = base_networks + (
                common["tor_demo_network"] if enabled else []
            )
            for index, node in enumerate(nodes):
                with self.subTest(enabled=enabled, node=node["name"]):
                    context = dict(
                        defaults, item=node, vm_nodes=nodes, networks=networks,
                        node_mac_map={
                            node["name"]: {
                                network["name"]: f"00:11:22:33:{index:02x}:{n:02x}"
                                for n, network in enumerate(networks)
                            }
                        },
                        flavors={"node": {"architecture": "x86_64", "memory": 4096,
                                          "vcpu": 2}},
                        host_architecture="x86_64", libvirt_domain_type="kvm",
                        host_os="ubuntu", host_distro="ubuntu24",
                        libvirt_nic_model="virtio", tpm_emulator=False,
                        enable_vnc_console=False,
                    )
                    document = ET.fromstring(vm_template.render(**context))
                    interfaces = document.findall("./devices/interface")
                    self.assertEqual(len(interfaces), 3 if enabled else 2)
                    self.assertEqual(
                        [nic.find("source").get("bridge") for nic in interfaces[:2]],
                        ["provisioning", "external"],
                    )
                    for nic in interfaces[:2]:
                        self.assertIsNone(nic.find("target"))
                        self.assertIsNone(nic.find("virtualport"))
                    if enabled:
                        nic = interfaces[2]
                        self.assertEqual(nic.get("type"), "ethernet")
                        self.assertIsNone(nic.find("source"))
                        self.assertIsNone(nic.find("virtualport"))
                        self.assertEqual(nic.find("target").get("dev"), f"m3tor{index}")
                        self.assertEqual(nic.find("target").get("managed"), "no")

        network_template = environment.from_string(
            (ROLES / "libvirt/templates/network.xml.j2").read_text()
        )
        document = ET.fromstring(network_template.render(
            item=common["tor_demo_network"][0],
        ))
        self.assertEqual(document.find("forward").get("mode"), "bridge")
        self.assertEqual(document.find("bridge").get("name"), "labsw0")
        self.assertEqual(document.find("virtualport").get("type"), "openvswitch")
        self.assertIsNone(document.find("ip"))
        self.assertIsNone(document.find("vlan"))

    def test_demo_network_is_appended_only_once(self):
        tasks = load_yaml(ROLES / "common/tasks/main.yml")
        task = next(task for task in tasks
                    if task.get("name") == "Append the isolated ToR demo network")
        defaults = load_yaml(ROLES / "common/defaults/main.yml")
        environment = template_environment()
        append = environment.compile_expression(
            task["set_fact"]["networks"].removeprefix("{{").removesuffix("}}").strip()
        )
        conditions = [environment.compile_expression(value) for value in task["when"]]
        for enabled in (False, True):
            context = {
                "enable_tor_demo": enabled,
                "networks": [{"name": "provisioning"}, {"name": "external"}],
                "tor_demo_network": defaults["tor_demo_network"],
            }
            for _ in range(3):
                if all(condition(**context) for condition in conditions):
                    context["networks"] = append(**context)
            self.assertEqual(
                [network["name"] for network in context["networks"]],
                ["provisioning", "external"] + (["tor-demo"] if enabled else []),
            )

    def test_generated_bmo_and_ironic_configuration(self):
        source = (ROOT / "03_launch_mgmt_cluster.sh").read_text()
        functions = "\n".join(
            re.search(rf"^{name}\(\)\n\{{.*?^\}}", source, re.M | re.S).group()
            for name in ("launch_baremetal_operator", "launch_ironic_via_irso")
        )
        for enabled in ("false", "true"):
            with self.subTest(enabled=enabled), tempfile.TemporaryDirectory() as work:
                work = Path(work)
                (work / "config/default").mkdir(parents=True)
                (work / "tools").mkdir()
                deploy = work / "tools/deploy.sh"
                deploy.write_text("#!/bin/sh\nexit 0\n")
                deploy.chmod(0o700)
                environment = dict(
                    os.environ, BMOPATH=str(work), IRONIC_DATA_DIR=str(work),
                    ENABLE_TOR_DEMO=enabled, BOOTSTRAP_CLUSTER="kind",
                    BMO_RUN_LOCAL="false", BMO_FEATURE_GATES="HostClaims=true",
                    IRONIC_NAMESPACE="test-ironic", IRONIC_URL="http://test:6385",
                    IRONIC_SWITCH_CONFIGS_SECRET="ironic-switch-config",
                    IRONIC_SWITCH_CREDENTIALS_SECRET="ironic-switch-credentials",
                    IRONIC_SWITCH_CREDENTIALS_PATH="/etc/ironic/networking/credentials",
                    IRONIC_NETWORK_INTERFACE="ironic-networking",
                    NODES_PLATFORM="libvirt", IRONIC_USE_MARIADB="false",
                )
                harness = """
set -e
sudo() { "$@"; }
safe_pushd() { pushd "$1" >/dev/null; }
update_component_image() { :; }
kubectl() { :; }
get_component_image() { echo test-image; }
BMO_IRONIC_ARGS=()
"""
                subprocess.run(
                    ["bash", "-c", harness + functions +
                     "\nlaunch_baremetal_operator\nlaunch_ironic_via_irso"],
                    env=environment, check=True, capture_output=True, text=True,
                )
                config = (work / "config/default/ironic.env").read_text()
                self.assertIn("FEATURE_GATES=HostClaims=true\n", config)
                ironic = load_yaml(work / "ironic.yaml")
                self.assertEqual(ironic["metadata"]["namespace"], "test-ironic")
                if enabled == "true":
                    self.assertIn("IRONIC_SWITCH_CONFIGS_SECRET=ironic-switch-config",
                                  config)
                    self.assertEqual(ironic["spec"]["networkingService"],
                                     {"enabled": True})
                else:
                    self.assertNotIn("IRONIC_SWITCH", config)
                    self.assertNotIn("networkingService", ironic["spec"])

    def test_bridge_ownership_and_cleanup_order(self):
        setup = load_yaml(ROLES / "libvirt/tasks/network_setup_tasks.yml")[0]["block"]
        teardown = load_yaml(ROLES / "libvirt/tasks/main.yml")[1]["block"]
        environment = template_environment()
        for tasks in (setup, teardown):
            guard = next(task for task in tasks if "assert" in task)
            expression = environment.compile_expression(guard["assert"]["that"][0])
            for output, allowed in (
                ("", True), ("{}", False),
                ("{metal3-dev-env=tor-demo}", True),
                ('{"metal3-dev-env"="tor-demo"}', True),
                ("{metal3-dev-env=other}", False),
                ("{other-metal3-dev-env=tor-demo}", False),
                ("{metal3-dev-env=tor-demo-other}", False),
            ):
                with self.subTest(output=output):
                    self.assertEqual(expression(tor_demo_bridge_ids={"stdout": output}),
                                     allowed)
        vm_cleanup = next(i for i, task in enumerate(teardown)
                          if task.get("include_tasks") == "vm_teardown_tasks.yml")
        bridge_cleanup = next(i for i, task in enumerate(teardown)
                              if "del-br" in task.get("command", ""))
        self.assertLess(vm_cleanup, bridge_cleanup)
        self.assertIn("enable_tor_demo", teardown[bridge_cleanup]["when"])

    def test_persistent_tap_setup_and_cleanup(self):
        environment = template_environment()
        script = environment.from_string(
            (ROLES / "libvirt/templates/metal3-tor-taps.sh.j2").read_text()
        ).render(vm_nodes=[{"name": "node_0"}, {"name": "node_1"}])
        self.assertIn('TAPS=("m3tor0" "m3tor1")', script)
        self.assertIn("ovs-vsctl --may-exist add-port", script)
        self.assertIn("ip tuntap add", script)

        setup = load_yaml(ROLES / "libvirt/tasks/network_setup_tasks.yml")[0]["block"]
        include = next(task for task in setup
                       if task.get("include_tasks") == "tor_demo_taps.yml")
        self.assertIn("enable_tor_demo", include["when"])

        teardown = load_yaml(ROLES / "libvirt/tasks/main.yml")[1]["block"]
        tap_cleanup = next(i for i, task in enumerate(teardown)
                           if "m3tor" in str(task.get("shell", "")))
        bridge_cleanup = next(i for i, task in enumerate(teardown)
                              if "del-br" in task.get("command", ""))
        self.assertLess(tap_cleanup, bridge_cleanup)
        self.assertIn("enable_tor_demo", teardown[tap_cleanup]["when"])

    def test_tls_cert_networking_san_and_ca_bundle(self):
        source = ROOT / "lib/ironic_tls_setup.sh"
        name = "ironic-networking-service.baremetal-operator-system.svc"
        for enabled, expected_certs in ((True, 2), (False, 1)):
            with self.subTest(enabled=enabled), tempfile.TemporaryDirectory() as workdir:
                environment = dict(
                    PATH=os.environ["PATH"], IRONIC_TLS_SETUP="true",
                    WORKING_DIR=workdir,
                    CLUSTER_BARE_METAL_PROVISIONER_HOST="172.22.0.2",
                    IRONIC_HOST="172.22.0.2", IRONIC_HOST_IP="172.22.0.2",
                    IRONIC_NAMESPACE="baremetal-operator-system",
                    ENABLE_TOR_DEMO="true" if enabled else "false",
                )
                subprocess.run(["bash", "-c", f"source {source}"], env=environment,
                               capture_output=True, text=True, check=True)
                cert = Path(workdir, "certs", "ironic.crt").read_text()
                self.assertEqual(cert.count("BEGIN CERTIFICATE"), expected_certs)
                san = subprocess.run(
                    ["openssl", "x509", "-noout", "-ext", "subjectAltName"],
                    input=cert, capture_output=True, text=True, check=True,
                ).stdout
                if enabled:
                    self.assertIn(name, san)
                else:
                    self.assertNotIn("DNS:", san)

    def test_ovs_package_names(self):
        defaults = load_yaml(ROLES / "ovs/defaults/main.yml")
        environment = template_environment()
        for family, expected in (("Debian", "openvswitch-switch"),
                                 ("RedHat", "openvswitch"),
                                 ("Suse", "openvswitch")):
            for setting in ("ovs_package", "ovs_service"):
                self.assertEqual(environment.from_string(defaults[setting]).render(
                    ansible_os_family=family), expected)


if __name__ == "__main__":
    unittest.main()
