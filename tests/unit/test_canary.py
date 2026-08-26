import hashlib
import tempfile
import unittest
from pathlib import Path

from lda.benchmarks.canary import (HARNESS, CanaryBenchmarkRunner, architecture_compatibility,
                                   upload_source_snapshot, validate_optimization_flags)
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

    def test_e2e_crosses_an_unchanged_process_boundary(self):
        self.assertIn("rsvg-convert", HARNESS)
        self.assertIn("soup_session_send_and_read", HARNESS)
        self.assertIn("precompiled_c_client_local_http_server", HARNESS)

    def test_build_command_bootstraps_source_dependencies(self):
        command = CanaryBenchmarkRunner(E2BClient(fake=True)).build_command("libcairo2")
        self.assertIn("build-dep cairo", command)
        self.assertIn("dpkg-buildpackage -us -uc -b -d", command)

    def test_candidate_flags_reject_native_and_fast_math(self):
        with self.assertRaises(ValueError):
            validate_optimization_flags(["-O3", "-march=native"])
        with self.assertRaises(ValueError):
            validate_optimization_flags(["-Ofast"])
        self.assertEqual(validate_optimization_flags(["-O3", "-fno-plt"]), ("-O3", "-fno-plt"))

    def test_virtual_cpuid_is_compatible_but_not_attested(self):
        result = architecture_compatibility({
            "vendor_id": "GenuineIntel", "family": 6, "model": 207, "stepping": 2,
            "cpu_model": "Intel(R) Xeon(R) Processor", "hypervisor": "kvm",
            "flags": ["hypervisor", "avx2", "avx512f", "avx512dq", "avx512bw", "avx512vl",
                      "avx512_vnni", "amx_tile", "amx_int8", "amx_bf16"],
        })
        self.assertTrue(result["compatible"])
        self.assertTrue(result["virtualized"])
        self.assertFalse(result["identity_attested"])

    def test_local_brand_string_is_not_hardware_attestation(self):
        result = architecture_compatibility({
            "vendor_id": "GenuineIntel", "family": 6, "model": 207, "stepping": 2,
            "cpu_model": "INTEL(R) XEON(R) GOLD 6548Y+", "flags": [
                "avx2", "avx512f", "avx512dq", "avx512bw", "avx512vl",
                "avx512_vnni", "amx_tile", "amx_int8", "amx_bf16"],
        })
        self.assertTrue(result["compatible"])
        self.assertFalse(result["identity_attested"])

    def test_virtual_target_cpuid_is_architecturally_eligible(self):
        result = architecture_compatibility({
            "vendor_id": "GenuineIntel", "family": 6, "model": 207, "stepping": 2,
            "cpu_model": "Intel(R) Xeon(R) Processor", "hypervisor": "kvm",
            "flags": ["hypervisor", "avx2", "avx512f", "avx512dq", "avx512bw", "avx512vl",
                      "avx512_vnni", "amx_tile", "amx_int8", "amx_bf16"],
        })
        self.assertTrue(result["compatible"])
        self.assertFalse(result["identity_attested"])

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
