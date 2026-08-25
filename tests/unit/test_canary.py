import hashlib
import tempfile
import unittest
from pathlib import Path

from lda.benchmarks.canary import HARNESS, CanaryBenchmarkRunner, upload_source_snapshot
from lda.e2b.client import E2BClient


class CanaryHarnessTest(unittest.TestCase):
    def test_harness_is_executable_python(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "harness.py"
            path.write_text(HARNESS, encoding="utf-8")
            import py_compile
            py_compile.compile(str(path), doraise=True)

    def test_command_has_no_claimed_reward(self):
        runner = CanaryBenchmarkRunner(E2BClient(fake=True))
        command = runner.command("libcairo2", "/workspace/benchmarks/harness.py")
        self.assertIn("--samples 30", command)
        self.assertNotIn("speedup", command)

    def test_build_command_bootstraps_source_dependencies(self):
        command = CanaryBenchmarkRunner(E2BClient(fake=True)).build_command("libcairo2")
        self.assertIn("build-dep cairo", command)
        self.assertIn("dpkg-buildpackage -us -uc -b -d", command)

    def test_snapshot_upload_verifies_manifest(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "20260825T000000Z"
            root.mkdir()
            payload = b"pinned source\n"
            item = root / "cairo" / "source.dsc"
            item.parent.mkdir()
            item.write_bytes(payload)
            digest = hashlib.sha256(payload).hexdigest()
            (root / "SHA256SUMS").write_text(f"{digest}  cairo/source.dsc\n", encoding="utf-8")
            client = E2BClient(fake=True)
            result = upload_source_snapshot(client, client.create({"run_id": "r"}), Path(tmp))
            self.assertEqual(next(item["sha256"] for item in result["files"] if item["path"].endswith("source.dsc")), digest)


if __name__ == "__main__":
    unittest.main()
