import hashlib
import tempfile
import unittest
from pathlib import Path

from lda.research.campaign import CANARY, TOP10, prepare
from lda.research.release import evaluate_canary_release, REQUIRED_QUALIFICATION_GATES


class CampaignInputTest(unittest.TestCase):
    def test_hash_and_top10_are_persisted(self):
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "report.md"
            source.write_text("|1|`libcairo2`|60.20|72|12|12|\n", encoding="utf-8")
            record = prepare(source, tmp)
            self.assertEqual(record.sha256, hashlib.sha256(source.read_bytes()).hexdigest())
            self.assertEqual(record.top10, TOP10)
            self.assertEqual(record.canary, CANARY)
            self.assertTrue((Path(tmp) / record.original_artifact).exists())

    @staticmethod
    def _row(package: str, *, gates: bool) -> dict:
        checks = {name: {"available": True} for name in
                  ("binary_package", "source_mapping", "dependency_metadata", "build_tools")}
        row = {"package": package, "checks": checks}
        refs = [f"/artifacts/{package}/qualification.json"]
        for name, _label in REQUIRED_QUALIFICATION_GATES:
            row[name] = gates
            row[f"{name}_evidence_refs"] = refs
        return row

    def test_release_gate_is_canary_scoped_and_requires_real_evidence(self):
        qualification = {"results": [self._row("libcairo2", gates=True), self._row("libsoup-3.0-0", gates=False),
                                      self._row("libgtk-4-1", gates=False)]}
        result = evaluate_canary_release(qualification, CANARY)
        self.assertFalse(result["canary_release_ready"])
        self.assertEqual(result["eligible_packages"], [])
        self.assertTrue(any("libsoup-3.0-0" in blocker for blocker in result["release_blockers"]))

        qualification["results"][1] = self._row("libsoup-3.0-0", gates=True)
        result = evaluate_canary_release(qualification, CANARY)
        self.assertTrue(result["canary_release_ready"])
        self.assertEqual(result["eligible_packages"], CANARY)
        # Performance and package replacement evidence are produced later by
        # Humanize/Judge, so their absence must not block canary startup.
        self.assertEqual(result["release_blockers"], [])

    def test_release_gate_rejects_unreferenced_true_gate(self):
        row = self._row("libcairo2", gates=True)
        row.pop("source_unpacked_verified_evidence_refs")
        row["source_unpacked_verified"] = True
        row["evidence_refs"] = []
        result = evaluate_canary_release({"results": [row, self._row("libsoup-3.0-0", gates=True)]}, CANARY)
        self.assertFalse(result["canary_release_ready"])
        self.assertTrue(any("source unpack" in blocker for blocker in result["release_blockers"]))
