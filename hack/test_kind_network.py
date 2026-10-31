"""Exercise the kind provisioning helper with mocked network commands."""

import os
from pathlib import Path
import subprocess
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]


class KindNetworkTests(unittest.TestCase):
    def run_helper(self, action, existing=False, alias="metal3-dev-env:kind-irso",
                   peer="24", collision=False, pid="1234"):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            if existing:
                interface = root / "m3-kind-pro"
                interface.mkdir()
                (interface / "ifalias").write_text(alias)
                (interface / "ifindex").write_text("24")
            source = (ROOT / "lib/kind_network.sh").read_text().replace(
                "/sys/class/net/", directory + "/"
            )
            harness = r"""
set -eu
sudo() {
    printf 'sudo %s\n' "$*" >> "$CALLS"
    if [[ "$*" == "ip link show dev m3-kind-peer" ]]; then
        return 1
    fi
}
docker() {
    printf 'docker %s\n' "$*" >> "$CALLS"
    if [[ "$1" == inspect ]]; then
        echo "$NODE_PID"
    elif [[ "$*" == *"/ifalias" ]]; then
        echo metal3-dev-env:kind-irso
    elif [[ "$*" == *"/iflink" ]]; then
        echo "$GUEST_PEER"
    elif [[ "$*" == *"ip link show dev ironicendpoint" ]]; then
        [[ "$COLLISION" == true ]]
    fi
}
"""
            calls = root / "calls"
            environment = dict(
                PATH=os.environ["PATH"], CALLS=str(calls), NODE_PID=pid,
                GUEST_PEER=peer, COLLISION=str(collision).lower(),
                BARE_METAL_PROVISIONER_INTERFACE="ironicendpoint",
                INITIAL_BARE_METAL_PROVISIONER_BRIDGE_IP="172.22.0.9",
                BARE_METAL_PROVISIONER_CIDR="24",
            )
            result = subprocess.run(
                ["bash", "-c", harness + source + "\n" + action],
                env=environment, capture_output=True, text=True, check=False,
            )
            return result, calls.read_text() if calls.exists() else ""

    def test_create_connection_and_base_address(self):
        result, calls = self.run_helper("configure_kind_irso_network")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("ip link add m3-kind-pro type veth peer name m3-kind-peer", calls)
        self.assertIn("ip link set dev m3-kind-peer netns 1234", calls)
        self.assertIn("ip link set dev m3-kind-peer name ironicendpoint", calls)
        self.assertIn("ip link set dev m3-kind-pro master provisioning", calls)
        self.assertIn("ip address replace 172.22.0.9/24 dev ironicendpoint", calls)
        self.assertNotIn("172.22.0.2", calls)

    def test_existing_owned_pair_is_reused(self):
        result, calls = self.run_helper("configure_kind_irso_network", existing=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertNotIn("ip link add", calls)
        self.assertIn("ip address replace", calls)

    def test_conflicts_fail_without_network_changes(self):
        for options in (
            {"existing": True, "alias": "unrelated"},
            {"existing": True, "peer": "99"},
            {"collision": True},
            {"pid": "0"},
        ):
            with self.subTest(options=options):
                result, calls = self.run_helper("configure_kind_irso_network", **options)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("ERROR:", result.stderr)
                self.assertNotIn("ip link add", calls)
                self.assertNotIn("ip link set", calls)

    def test_remove_owned_pair_only(self):
        result, calls = self.run_helper("remove_kind_irso_network", existing=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("ip link delete dev m3-kind-pro", calls)
        result, calls = self.run_helper(
            "remove_kind_irso_network", existing=True, alias="unrelated",
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertNotIn("ip link delete", calls)
        result, calls = self.run_helper("remove_kind_irso_network")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(calls, "")


if __name__ == "__main__":
    unittest.main()
