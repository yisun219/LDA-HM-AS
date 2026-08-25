from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path

from lda_hm import E2BSandbox, SandboxUnavailable


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


if __name__ == "__main__":
    unittest.main()
