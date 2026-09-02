from __future__ import annotations

import os
import socket
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from lda_hm import E2BSandbox, SandboxUnavailable


class _Result:
    def __init__(self, stdout="", stderr="", exit_code=0):
        self.stdout = stdout
        self.stderr = stderr
        self.exit_code = exit_code


class _Handle:
    pid = 42

    def __init__(self):
        self.disconnected = False

    def disconnect(self):
        self.disconnected = True


class _LongCommands:
    def __init__(self):
        self.calls = []
        self.handle = _Handle()

    def run(self, command, **kwargs):
        self.calls.append((command, kwargs))
        if kwargs.get("background"):
            return self.handle
        if "printf 'DONE '" in command:
            return _Result("DONE 0")
        if "tail -c" in command and command.endswith("/stdout"):
            return _Result("long command output")
        if "tail -c" in command and command.endswith("/stderr"):
            return _Result("")
        return _Result()

    def kill(self, pid):
        raise AssertionError(f"successful command unexpectedly killed pid {pid}")


class _LongClient:
    def __init__(self):
        self.commands = _LongCommands()


class SandboxPrivateEnvTest(unittest.TestCase):
    def test_loads_private_config_without_overriding_environment(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            config = Path(directory) / "e2b.env"
            config.write_text(
                "E2B_API_URL=https://example.invalid\nE2B_ACCESS_TOKEN=file-value\n",
                encoding="utf-8",
            )
            config.chmod(0o600)
            previous_url = os.environ.get("E2B_API_URL")
            previous_token = os.environ.get("E2B_ACCESS_TOKEN")
            os.environ["E2B_ACCESS_TOKEN"] = "environment-value"
            os.environ.pop("E2B_API_URL", None)
            try:
                E2BSandbox.load_private_env(config)
                self.assertEqual(os.environ["E2B_API_URL"], "https://example.invalid")
                self.assertEqual(os.environ["E2B_ACCESS_TOKEN"], "environment-value")
            finally:
                if previous_url is None:
                    os.environ.pop("E2B_API_URL", None)
                else:
                    os.environ["E2B_API_URL"] = previous_url
                if previous_token is None:
                    os.environ.pop("E2B_ACCESS_TOKEN", None)
                else:
                    os.environ["E2B_ACCESS_TOKEN"] = previous_token

    def test_rejects_group_readable_config(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            config = Path(directory) / "e2b.env"
            config.write_text("E2B_API_KEY=secret\n", encoding="utf-8")
            config.chmod(0o640)
            with self.assertRaises(SandboxUnavailable):
                E2BSandbox.load_private_env(config)


class DetachedLongCommandTest(unittest.TestCase):
    def test_long_command_uses_background_handle_and_short_poll(self) -> None:
        client = _LongClient()
        sandbox = E2BSandbox(client, sandbox_id="e2b-test")
        result = sandbox.run(("build-package", "baseline"), timeout_seconds=1200)
        self.assertTrue(result.ok)
        self.assertEqual(result.stdout, "long command output")
        self.assertTrue(client.commands.handle.disconnected)
        self.assertTrue(
            any(kwargs.get("background") for _command, kwargs in client.commands.calls)
        )
        background_calls = [
            kwargs for _command, kwargs in client.commands.calls
            if kwargs.get("background")
        ]
        self.assertEqual(background_calls[0]["timeout"], 1200)

    def test_connect_prepares_candidate_output_directory(self) -> None:
        client = _LongClient()
        E2BSandbox.connect(client_factory=lambda **_kwargs: client)
        command, kwargs = client.commands.calls[0]
        self.assertIn("sudo -n mkdir -p", command)
        self.assertIn("/opt/lda/candidate", command)
        self.assertIn("sudo -n chown", command)
        self.assertEqual(kwargs["cwd"], "/")
        self.assertEqual(kwargs["timeout"], 60)


class BaselineArtifactGuardTest(unittest.TestCase):
    def test_baseline_guard_precedes_destructive_cleanup(self) -> None:
        script = (
            Path(__file__).resolve().parents[1]
            / "sandbox/lda-base/checks/build-package.sh"
        ).read_text(encoding="utf-8")
        guard = script.index('if test "$mode" = baseline; then')
        cleanup = script.index("# Clear build outputs only")
        self.assertLess(guard, cleanup)
        self.assertIn("refs/tags/lda-baseline^{}", script[guard:cleanup])
        self.assertIn(
            "refusing to overwrite baseline artifacts from a candidate commit",
            script[guard:cleanup],
        )

    def test_package_cache_requires_complete_payload_and_test_evidence(self) -> None:
        script = (
            Path(__file__).resolve().parents[1]
            / "sandbox/lda-base/checks/build-package.sh"
        ).read_text(encoding="utf-8")
        guard = script[script.index("cached_artifacts_complete()") : script.index("# Clear build outputs only")]
        for required in (
            "runtime-debs.list",
            "runtime-deb.sha256",
            "libraries.list",
            "executables.list",
            "upstream-tests-state",
            "upstream-tests-passed",
            "sha256sum --status -c",
        ):
            self.assertIn(required, guard)

    def test_source_branch_normalizes_debian_version_characters(self) -> None:
        script = (
            Path(__file__).resolve().parents[1]
            / "sandbox/lda-base/checks/prepare-ubuntu-source.sh"
        ).read_text(encoding="utf-8")
        self.assertIn("branch_suffix=", script)
        self.assertIn("git check-ref-format", script)
        self.assertNotIn('git init -b "lda/${package}-${version//:/_}"', script)

    def test_source_snapshot_tracks_ignored_source_files(self) -> None:
        script = (
            Path(__file__).resolve().parents[1]
            / "sandbox/lda-base/checks/prepare-ubuntu-source.sh"
        ).read_text(encoding="utf-8")
        self.assertIn("git add --all --force", script)
        self.assertNotIn("\ngit add .\n", script)


class X11DisplayReadyTest(unittest.TestCase):
    def test_detects_abstract_x11_socket_without_filesystem_entry(self) -> None:
        display = f":{30000 + os.getpid() % 20000}"
        address = "\0/tmp/.X11-unix/X" + display[1:]
        listener = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        listener.bind(address)
        listener.listen(1)
        script = (
            Path(__file__).resolve().parents[1]
            / "sandbox/lda-base/checks/x11-display-ready.py"
        )
        try:
            ready = subprocess.run(
                (sys.executable, str(script), display), check=False
            )
            self.assertEqual(ready.returncode, 0)
        finally:
            listener.close()
        missing = subprocess.run(
            (sys.executable, str(script), display), check=False
        )
        self.assertEqual(missing.returncode, 1)


if __name__ == "__main__":
    unittest.main()
