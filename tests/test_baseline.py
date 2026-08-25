from __future__ import annotations

import unittest

from lda_hm import BaselineSpec


class BaselineSpecTest(unittest.TestCase):
    def test_source_package_mode_is_explicit_and_digestible(self) -> None:
        baseline = BaselineSpec()
        self.assertEqual(baseline.mode, "source_package")
        self.assertEqual(baseline.release, "26.04")
        self.assertTrue(baseline.digest())
        self.assertIn("verify-baseline.sh", baseline.verification_command()[-1])

    def test_iso_snapshot_requires_immutable_identity(self) -> None:
        with self.assertRaises(ValueError):
            BaselineSpec(mode="iso_snapshot", template="ubuntu-26.04-desktop-amd64-stock", edition="desktop")

    def test_iso_snapshot_accepts_complete_identity(self) -> None:
        baseline = BaselineSpec(
            mode="iso_snapshot",
            template="ubuntu-26.04-desktop-amd64-stock",
            edition="desktop",
            iso_artifact="ubuntu-26.04-desktop-amd64.iso",
            iso_sha256="a" * 64,
            iso_build_id="20260801",
            manifest_sha256="b" * 64,
            snap_manifest_sha256="c" * 64,
            apt_snapshot="2026-08-01T00:00:00Z",
            rootfs_digest="rootfs:sha256:abc",
            package_inventory_digest="d" * 64,
            snap_inventory_digest="e" * 64,
        )
        self.assertTrue(baseline.is_distribution)
        self.assertEqual(len(baseline.digest()), 64)


if __name__ == "__main__":
    unittest.main()
