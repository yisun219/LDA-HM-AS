import unittest

from lda.e2b.client import E2BClient, Sandbox


class RecordingCheckpointClient(E2BClient):
    def __init__(self):
        super().__init__(fake=False)
        self.polls = 0
        self.commands = []

    def command(self, sandbox, command, *, background=False, timeout=None):
        self.commands.append((command, background, timeout))
        if background:
            return {"pid": 42, "status": "started"}
        if "printf 'DONE '" in command:
            self.polls += 1
            return {"exit_code": 0, "stdout": "RUNNING" if self.polls == 1 else "DONE 7", "stderr": ""}
        return {"exit_code": 0, "stdout": "", "stderr": ""}

    def filesystem_read(self, sandbox, path):
        return "observed stdout" if path.endswith("/stdout") else "observed stderr"


class CheckpointedCommandTest(unittest.TestCase):
    def test_background_job_is_polled_and_returns_observed_result(self):
        client = RecordingCheckpointClient()
        result = client.command_checkpointed(
            Sandbox("sandbox", {"run_id": "r"}), "apt-get build-dep cairo", timeout=5, poll_seconds=0)
        self.assertEqual(result["exit_code"], 7)
        self.assertEqual(result["stdout"], "observed stdout")
        self.assertEqual(result["stderr"], "observed stderr")
        self.assertTrue(client.commands[0][1])
        self.assertGreaterEqual(client.polls, 2)

    def test_fake_client_keeps_deterministic_short_path(self):
        client = E2BClient(fake=True)
        result = client.command_checkpointed(
            client.create({"run_id": "r"}), "printf lda-preflight", timeout=5, poll_seconds=0)
        self.assertEqual(result["exit_code"], 0)
        self.assertEqual(result["stdout"], "lda-preflight")


if __name__ == "__main__":
    unittest.main()
