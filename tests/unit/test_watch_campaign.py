import os
import subprocess
import tempfile
import unittest
from pathlib import Path


class WatchCampaignTest(unittest.TestCase):
    def _run(self, *, recovered: bool) -> list[str]:
        repository = Path(__file__).resolve().parents[2]
        script = repository / "scripts" / "watch_campaign.sh"
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            bin_dir = root / "bin"
            run_root = root / "run"
            bin_dir.mkdir()
            run_root.mkdir()
            campaign = root / "campaign.md"
            campaign.write_text("campaign\n", encoding="utf-8")
            invocation_log = root / "invocations.log"

            curl = bin_dir / "curl"
            curl.write_text("#!/bin/sh\nprintf 200\n", encoding="utf-8")
            curl.chmod(0o755)
            bootstrap = bin_dir / "bootstrap-python"
            bootstrap.write_text(
                "#!/bin/sh\n"
                "if [ \"${1:-}\" = -c ]; then exit 0; fi\n"
                "printf '%s\\n' \"$*\" >> \"$LDA_TEST_INVOCATIONS\"\n",
                encoding="utf-8",
            )
            bootstrap.chmod(0o755)
            if recovered:
                record = run_root / ".lda" / "controller.json"
                record.parent.mkdir()
                record.write_text("{}\n", encoding="utf-8")

            environment = dict(os.environ)
            environment.update({
                "PATH": str(bin_dir) + os.pathsep + environment.get("PATH", ""),
                "LDA_BOOTSTRAP_PYTHON": str(bootstrap),
                "LDA_TEST_INVOCATIONS": str(invocation_log),
            })
            result = subprocess.run(
                ["bash", str(script), "run-test", str(campaign), str(run_root)],
                cwd=root, env=environment, text=True, capture_output=True, timeout=10,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            return invocation_log.read_text(encoding="utf-8").splitlines()

    def test_first_healthy_attempt_starts_formal_run(self):
        calls = self._run(recovered=False)
        self.assertEqual(len(calls), 1)
        self.assertIn("./lda --root", calls[0])
        self.assertIn(" run --flow argus-humanize ", calls[0])

    def test_recovery_record_resumes_instead_of_rebootstrapping(self):
        calls = self._run(recovered=True)
        self.assertEqual(len(calls), 1)
        self.assertIn("./lda --root", calls[0])
        self.assertIn(" resume --run-id run-test", calls[0])
        self.assertNotIn(" --flow ", calls[0])


if __name__ == "__main__":
    unittest.main()
