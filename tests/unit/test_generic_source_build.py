import base64
import unittest

from lda.e2b.client import E2BClient
from lda.packages.source_build import DebianSourceBuilder, SPECS


def qualification(package="libgtk-4-1", source="gtk4", version="4.22.4+ds-0ubuntu0.1"):
    return {
        "sources_snapshot": {"verified": True, "snapshot": "20260825T000000Z"},
        "results": [{
            "package": package,
            "source_snapshot_verified": True,
            "checks": {"source_mapping": {
                "available": True, "source": source, "source_version": version,
            }},
        }],
    }


class RecordingClient(E2BClient):
    def __init__(self, *, omit_dev=False):
        super().__init__(fake=True)
        self.commands = []
        self.omit_dev = omit_dev

    def command(self, sandbox, command, *, background=False, timeout=None):
        self.commands.append(command)
        if "find " in command and "-name '*.dsc'" in command:
            return {"exit_code": 0, "stdout": "/workspace/generic-source-build/libgtk-4-1/downloads/gtk4.dsc\n", "stderr": ""}
        if "find " in command and "-name '*.deb'" in command:
            paths = ["/workspace/generic-source-build/libgtk-4-1/libgtk-4-1.deb"]
            if not self.omit_dev:
                paths.append("/workspace/generic-source-build/libgtk-4-1/libgtk-4-dev.deb")
            return {"exit_code": 0, "stdout": "\n".join(paths) + "\n", "stderr": ""}
        if "dpkg-deb -f" in command:
            package = "libgtk-4-dev" if "libgtk-4-dev.deb" in command else "libgtk-4-1"
            return {"exit_code": 0, "stdout": f"{package}\n4.22.4+ds-0ubuntu0.1\namd64\n", "stderr": ""}
        if command.startswith("sha256sum "):
            return {"exit_code": 0, "stdout": "a" * 64 + "  artifact.deb\n", "stderr": ""}
        return {"exit_code": 0, "stdout": "", "stderr": ""}


class GenericSourceBuildTest(unittest.TestCase):
    def test_build_uses_fixed_snapshot_and_exact_source_version(self):
        client = RecordingClient()
        sandbox = client.create({"run_id": "r"})
        result = DebianSourceBuilder(client, qualification()).build(sandbox, "libgtk-4-1")
        self.assertTrue(result["passed"])
        self.assertEqual(result["status"], "BUILT")
        self.assertTrue(result["runtime_artifact"].endswith("libgtk-4-1.deb"))
        self.assertTrue(result["dev_artifacts"]["libgtk-4-dev"].endswith("libgtk-4-dev.deb"))
        commands = "\n".join(client.commands)
        setup = client.commands[0].split("printf %s ", 1)[1].split(" | base64", 1)[0]
        self.assertIn("snapshot.ubuntu.com/ubuntu/20260825T000000Z/",
                      base64.b64decode(setup).decode())
        self.assertIn("gtk4=4.22.4+ds-0ubuntu0.1", commands)
        self.assertIn("dpkg-source -x", commands)
        self.assertIn("dpkg-buildpackage -us -uc -b", commands)
        self.assertIn("DEB_CFLAGS_MAINT_APPEND='-O3 -fno-plt'", commands)
        self.assertIn("DEB_CXXFLAGS_MAINT_APPEND='-O3 -fno-plt'", commands)
        self.assertNotIn("./configure", commands)
        self.assertNotIn("cmake --build", commands)

    def test_unsafe_candidate_flags_fail_before_commands(self):
        client = RecordingClient()
        result = DebianSourceBuilder(client, qualification()).build(
            client.create({"run_id": "r"}), "libgtk-4-1", cflags=["-O3", "-march=native"])
        self.assertFalse(result["passed"])
        self.assertEqual(result["status"], "POLICY_REJECTED")
        self.assertEqual(client.commands, [])

    def test_missing_verified_mapping_fails_before_commands(self):
        data = qualification()
        data["results"][0]["checks"]["source_mapping"]["available"] = False
        client = RecordingClient()
        result = DebianSourceBuilder(client, data).build(client.create({"run_id": "r"}), "libgtk-4-1")
        self.assertFalse(result["passed"])
        self.assertEqual(result["status"], "QUALIFICATION_REJECTED")
        self.assertEqual(client.commands, [])

    def test_source_name_mismatch_fails_before_commands(self):
        client = RecordingClient()
        result = DebianSourceBuilder(client, qualification(source="gtk+3.0")).build(
            client.create({"run_id": "r"}), "libgtk-4-1")
        self.assertFalse(result["passed"])
        self.assertEqual(result["status"], "QUALIFICATION_REJECTED")
        self.assertEqual(client.commands, [])

    def test_required_dev_package_is_fail_closed(self):
        client = RecordingClient(omit_dev=True)
        result = DebianSourceBuilder(client, qualification()).build(
            client.create({"run_id": "r"}), "libgtk-4-1")
        self.assertFalse(result["passed"])
        self.assertEqual(result["status"], "TARGET_DEV_DEB_MISSING")

    def test_top_eight_registry_has_only_real_dev_mappings(self):
        self.assertEqual(SPECS["gnome-shell"].dev_packages, ())
        self.assertEqual(SPECS["sssd-common"].dev_packages, ())
        self.assertEqual(SPECS["gstreamer1.0-plugins-good"].dev_packages, ())
        self.assertEqual(SPECS["ibus"].dev_packages, ("libibus-1.0-dev",))


if __name__ == "__main__":
    unittest.main()
