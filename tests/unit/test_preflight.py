import unittest
from unittest.mock import patch

from lda.e2b.client import E2BClient, TESTED_E2B_SDK_VERSION
from lda.e2b.preflight import Preflight


class PreflightTest(unittest.TestCase):
    def test_fake_data_plane_exercises_all_preflight_checks(self):
        result = Preflight(E2BClient(fake=True)).run("unit-preflight")
        self.assertTrue(result["passed"], result)
        self.assertTrue(all(result["checks"].values()))
        self.assertEqual(result["details"]["required_sdk_version"], TESTED_E2B_SDK_VERSION)

    def test_sdk_version_mismatch_fails_closed(self):
        with patch("lda.e2b.preflight.importlib.metadata.version", return_value="0.0.0"):
            result = Preflight(E2BClient(fake=True)).run("version-mismatch")
        self.assertFalse(result["passed"])
        self.assertFalse(result["checks"]["sdk_server"])


if __name__ == "__main__":
    unittest.main()
