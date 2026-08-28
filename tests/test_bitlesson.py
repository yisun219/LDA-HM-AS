from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from lda_hm import HumanizeFlow
from lda_hm.flow import BITLESSON_FILE
from lda_hm.stages import HumanizeStages


class BitLessonTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.flow = HumanizeFlow(Path(self.tmp.name))
        self.flow.begin("task")
        self.flow.record_idea("idea")
        self.flow.record_plan(
            "goal\ncriterion\npositive\nnegative\nboundary",
            goal_tracker="tracker",
        )

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def _round(self, **kwargs) -> dict:
        self.flow.begin_round("contract")
        self.flow.finish_builder_round("summary", **kwargs)
        record = json.loads(
            (self.flow.store.rounds / str(self.flow.state.current_round) / "bitlesson.json")
            .read_text(encoding="utf-8")
        )
        return record

    def _kb(self) -> str:
        return (self.flow.store.root / BITLESSON_FILE).read_text(encoding="utf-8")

    def test_add_appends_to_kb(self) -> None:
        record = self._round(
            bitlesson_action="add",
            bitlesson_id="BL-20260828-dispatch-placement",
            bitlesson_note="Resolve CPUID dispatch once per process, never per image.",
        )
        self.assertEqual(record["action"], "add")
        self.assertIn("## BL-20260828-dispatch-placement", self._kb())

    def test_update_requires_existing_entry(self) -> None:
        record = self._round(
            bitlesson_action="update",
            bitlesson_id="BL-20260828-missing",
            bitlesson_note="something",
        )
        self.assertEqual(record["action"], "none")
        self.assertIn("not in KB", record["note"])

    def test_duplicate_add_is_rejected(self) -> None:
        self._round(
            bitlesson_action="add",
            bitlesson_id="BL-20260828-x",
            bitlesson_note="first lesson",
        )
        self.flow.record_blocked_round("benchmark", "block to advance the round")
        record = self._round(
            bitlesson_action="add",
            bitlesson_id="BL-20260828-x",
            bitlesson_note="second lesson",
        )
        self.assertEqual(record["action"], "none")
        self.assertIn("already exists", record["note"])

    def test_placeholder_note_is_rejected(self) -> None:
        record = self._round(
            bitlesson_action="add",
            bitlesson_id="BL-20260828-y",
            bitlesson_note="[fill in later]",
        )
        self.assertEqual(record["action"], "none")

    def test_builder_protocol_parsing(self) -> None:
        text = (
            "did work\n"
            "BITLESSON: add\n"
            "BITLESSON_ID: BL-20260828-z\n"
            "BITLESSON_NOTE: a real lesson\n"
            "done"
        )
        action, entry_id, note = HumanizeStages._parse_bitlesson(text)
        self.assertEqual((action, entry_id, note), ("add", "BL-20260828-z", "a real lesson"))
        self.assertEqual(HumanizeStages._parse_bitlesson("no protocol"), ("none", "", ""))


if __name__ == "__main__":
    unittest.main()
