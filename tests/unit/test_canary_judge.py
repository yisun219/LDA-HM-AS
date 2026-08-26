import json
import hashlib
import unittest

from lda.e2b.client import E2BClient
from lda.judge.canary import CleanCanaryJudge, JUDGE_SCRIPT


def valid_payload():
    checks = {name: True for name in CleanCanaryJudge.REQUIRED_CHECKS}
    return {
        "schema": "lda.canary-judge.v1",
        "valid": True,
        "checks": checks,
        "anti_cheat": {"secret_exposure": False, "ld_preload": False,
                       "control_files_changed": False, "untracked_binary": False},
        "environment": {"secret_env_names": [], "judge_script_sha256": "a" * 64,
                        "probe_sha256": "b" * 64},
        "sha256": {"official_deb": "1" * 64, "official_dev_deb": "2" * 64,
                   "candidate_deb": "3" * 64, "candidate_dev_deb": "4" * 64},
    }


class RecordingClient(E2BClient):
    def __init__(self):
        super().__init__(fake=True)
        self.created = []

    def create(self, metadata):
        self.created.append(dict(metadata))
        return super().create(metadata)

    def command(self, sandbox, command, **kwargs):
        if "apt-get download" in command:
            runtime = "/workspace/judge-official/libcairo2_1.0_amd64.deb"
            dev = "/workspace/judge-official/libcairo2-dev_1.0_amd64.deb"
            self.filesystem_write(sandbox, runtime, b"official-runtime")
            self.filesystem_write(sandbox, dev, b"official-dev")
            return {"exit_code": 0, "stdout": runtime + "\n" + dev + "\n", "stderr": ""}
        if "clean_canary_judge.py" in command:
            payload = valid_payload()
            payload["sha256"] = {
                name: hashlib.sha256(self.filesystem_read_bytes(sandbox, path)).hexdigest()
                for name, path in {
                    "official_deb": "/workspace/judge/input/official.deb",
                    "official_dev_deb": "/workspace/judge/input/official-dev.deb",
                    "candidate_deb": "/workspace/judge/input/candidate.deb",
                    "candidate_dev_deb": "/workspace/judge/input/candidate-dev.deb",
                }.items()
            }
            payload["environment"]["judge_script_sha256"] = hashlib.sha256(JUDGE_SCRIPT.encode()).hexdigest()
            self.filesystem_write(sandbox, "/workspace/judge/evidence.json",
                                  json.dumps(payload))
            return {"exit_code": 0, "stdout": '{"valid": true}', "stderr": ""}
        return super().command(sandbox, command, **kwargs)


class CleanCanaryJudgeTest(unittest.TestCase):
    def test_filesystem_text_read_normalizes_bytearray(self):
        client = E2BClient(fake=True)
        box = client.create({"run_id": "r"})
        client._fake_files[(box.sandbox_id, "/tmp/value")] = bytearray(b"value")
        self.assertEqual(client.filesystem_read(box, "/tmp/value"), "value")

    def test_embedded_judge_is_valid_python_and_has_no_model_call(self):
        compile(JUDGE_SCRIPT, "clean_canary_judge.py", "exec")
        self.assertNotIn('["codex"', JUDGE_SCRIPT.lower())
        self.assertNotIn("import openai", JUDGE_SCRIPT.lower())
        self.assertIn("/opt/lda/judge/ffi_smoke", JUDGE_SCRIPT)

    def test_evaluate_fails_closed_on_any_missing_check_or_secret(self):
        payload = valid_payload()
        payload["checks"].pop("rollback")
        result = CleanCanaryJudge.evaluate(payload)
        self.assertFalse(result["valid"])
        self.assertEqual(result["missing_checks"], ["rollback"])

        payload = valid_payload()
        payload["environment"]["secret_env_names"] = ["OPENAI_API_KEY"]
        self.assertFalse(CleanCanaryJudge.evaluate(payload)["valid"])

    def test_evaluate_accepts_complete_deterministic_evidence(self):
        result = CleanCanaryJudge.evaluate(valid_payload())
        self.assertTrue(result["valid"])
        self.assertTrue(result["fence_passed"])

    def test_run_transfers_runtime_and_dev_to_offline_judge(self):
        client = RecordingClient()
        work = client.create({"project": "lda", "run_id": "r", "role": "candidate-work"})
        runtime = "/workspace/candidate/libcairo2.deb"
        dev = "/workspace/candidate/libcairo2-dev.deb"
        client.filesystem_write(work, runtime, b"candidate-runtime")
        client.filesystem_write(work, dev, b"candidate-dev")
        result, judge_box = CleanCanaryJudge(client).run(
            work=work, package="libcairo2", candidate_debs={"runtime": runtime, "dev": dev},
            metadata={"project": "lda", "run_id": "r", "life_cycle": "1",
                      "mission_id": "m", "candidate_id": "c", "lease_id": "judge-c"})
        self.assertTrue(result["valid"])
        self.assertEqual(judge_box.metadata["role"], "judge")
        self.assertEqual(judge_box.metadata["template"], "lda-judge")
        self.assertEqual(client.filesystem_read_bytes(judge_box, "/workspace/judge/input/candidate.deb"),
                         b"candidate-runtime")
        self.assertEqual(client.filesystem_read_bytes(judge_box, "/workspace/judge/input/candidate-dev.deb"),
                         b"candidate-dev")

    def test_missing_dev_package_fails_closed(self):
        client = RecordingClient()
        work = client.create({"project": "lda", "run_id": "r", "role": "candidate-work"})
        result, _ = CleanCanaryJudge(client).run(
            work=work, package="libcairo2", candidate_debs={"runtime": "/tmp/runtime.deb"},
            metadata={"project": "lda", "run_id": "r", "lease_id": "judge-r"})
        self.assertFalse(result["valid"])
        self.assertIn("official_baseline_deb_unavailable", result["reason"])

    def test_controller_rejects_sandbox_hash_mismatch(self):
        client = RecordingClient()
        work = client.create({"project": "lda", "run_id": "r", "role": "candidate-work"})
        client.filesystem_write(work, "/tmp/runtime.deb", b"runtime")
        client.filesystem_write(work, "/tmp/dev.deb", b"dev")
        original = client.command

        def tampered(sandbox, command, **kwargs):
            result = original(sandbox, command, **kwargs)
            if "clean_canary_judge.py" in command:
                payload = json.loads(client.filesystem_read(sandbox, "/workspace/judge/evidence.json"))
                payload["sha256"]["candidate_deb"] = "0" * 64
                client.filesystem_write(sandbox, "/workspace/judge/evidence.json", json.dumps(payload))
            return result

        client.command = tampered
        result, _ = CleanCanaryJudge(client).run(
            work=work, package="libcairo2",
            candidate_debs={"runtime": "/tmp/runtime.deb", "dev": "/tmp/dev.deb"},
            metadata={"project": "lda", "run_id": "r", "lease_id": "judge-tamper"})
        self.assertFalse(result["valid"])
        self.assertIn("transferred_deb_sha256_mismatch", result["integrity_failures"])


if __name__ == "__main__":
    unittest.main()
