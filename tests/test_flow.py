from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from lda_hm import (
    FlowConfig,
    HumanizeFlow,
    MainlineVerdict,
    Phase,
    ReviewResult,
)


PLAN = """# Plan

## Goal
Keep the flow aligned.

## Acceptance Criteria
Positive and negative checks exist.

## Boundaries
Only the allowed paths change.

## Tasks
Implement one bounded objective.
"""


class HumanizeFlowTest(unittest.TestCase):
    def test_external_results_root_is_resumable(self) -> None:
        with tempfile.TemporaryDirectory() as workspace_name, tempfile.TemporaryDirectory() as results_name:
            workspace = Path(workspace_name)
            results = Path(results_name)
            flow = HumanizeFlow(workspace, run_id="external-run", results_root=results)
            flow.begin("Optimize libpng")

            self.assertEqual(
                flow.store.root,
                results.resolve() / "runs" / "external-run",
            )
            self.assertFalse((workspace / ".lda-hm").exists())
            resumed = HumanizeFlow.resume(
                workspace,
                "external-run",
                results_root=results,
            )
            self.assertEqual(resumed.state.phase, Phase.IDEA)

    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.workspace = Path(self.temporary.name)

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def prepared(self, config: FlowConfig | None = None) -> HumanizeFlow:
        flow = HumanizeFlow(self.workspace, config)
        flow.begin("Build a controlled agent flow")
        flow.record_idea("Primary direction with objective evidence")
        flow.record_plan(PLAN, goal_tracker="Ultimate goal: alignment")
        return flow

    def test_state_is_resumable(self) -> None:
        flow = self.prepared()
        resumed = HumanizeFlow.resume(self.workspace, flow.run_id)
        self.assertEqual(resumed.state.phase, Phase.IMPLEMENTATION)
        self.assertTrue(resumed.store.plan_is_intact())

    def test_writer_round_enters_regular_review(self) -> None:
        flow = self.prepared()
        flow.begin_round("Implement the first bounded objective")
        phase = flow.finish_builder_round("Tests pass and evidence is recorded")
        self.assertEqual(phase, Phase.REGULAR_REVIEW)

    def test_fifth_round_enters_full_alignment(self) -> None:
        flow = self.prepared(FlowConfig(full_alignment_interval=5))
        flow.state.current_round = 4
        flow.store.save_state(flow.state)
        flow.begin_round("Re-anchor against the complete plan")
        phase = flow.finish_builder_round("All criteria were re-read")
        self.assertEqual(phase, Phase.FULL_ALIGNMENT)

    def test_stagnation_triggers_recovery_then_stop(self) -> None:
        flow = self.prepared()
        for expected in (Phase.IMPLEMENTATION, Phase.DRIFT_RECOVERY, Phase.STOP):
            flow.begin_round("Try one falsifiable action")
            flow.finish_builder_round("No mainline progress")
            phase = flow.record_review(
                ReviewResult(MainlineVerdict.STALLED, feedback="No progress")
            )
            self.assertEqual(phase, expected)

    def test_complete_review_requires_code_review(self) -> None:
        flow = self.prepared()
        flow.begin_round("Finish all plan tasks")
        flow.finish_builder_round("All acceptance criteria pass")
        phase = flow.record_review(
            ReviewResult(MainlineVerdict.ADVANCED, complete=True)
        )
        self.assertEqual(phase, Phase.CODE_REVIEW)
        self.assertEqual(flow.record_code_review(()), Phase.FINALIZE)
        flow.record_finalize("Repository is clean and tests pass")
        flow.record_methodology("The review feedback improved the next round")
        self.assertEqual(flow.state.phase, Phase.COMPLETE)


if __name__ == "__main__":
    unittest.main()
