from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from lda_hm import HumanizeFlow, HumanizeStages, Phase
from lda_hm.runtime import SessionTopology


PLAN = """# Candidate Plan
Goal: preserve alignment.
Positive test: required behavior passes.
Negative test: forbidden behavior fails.
Path boundary: only declared files.
Task: one bounded implementation step.
"""


class FakeSession:
    def __init__(self, responses: list[str]) -> None:
        self.responses = responses
        self.prompts: list[str] = []

    def ask(self, prompt: str, *, schema=None):
        self.prompts.append(prompt)
        if not self.responses:
            raise AssertionError("no fake response available")
        return self.responses.pop(0)


class FakeAgent:
    def __init__(self, sessions: list[list[str]]) -> None:
        self.pending = sessions
        self.opened: list[FakeSession] = []

    def new_session(self, cwd: Path) -> FakeSession:
        if not self.pending:
            raise AssertionError("unexpected fresh session")
        session = FakeSession(self.pending.pop(0))
        self.opened.append(session)
        return session


class StageTopologyTest(unittest.TestCase):
    def test_writers_persist_and_readers_are_fresh(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            workspace = Path(directory)
            drafter = FakeAgent([["idea draft"]])
            planner = FakeAgent([[PLAN]])
            analyst = FakeAgent([["analysis"], ["AGREE\nCONVERGED"]])
            builder = FakeAgent([["builder summary"]])
            reviewer = FakeAgent([["VERDICT: ADVANCED\nBLOCKING: NONE\nSTATUS: INCOMPLETE"]])
            topology = SessionTopology(
                drafter=drafter,
                planner=planner,
                analyst=analyst,
                builder=builder,
                reviewer=reviewer,
                cwd=workspace,
            )
            flow = HumanizeFlow(workspace)
            flow.begin("new flow")
            stages = HumanizeStages(flow, topology)

            idea = stages.gen_idea("new flow")
            stages.gen_plan(idea)
            result = stages.review_round(contract="advance one acceptance criterion")

            self.assertEqual(result.verdict.value, "ADVANCED")
            self.assertEqual(flow.state.phase, Phase.IMPLEMENTATION)
            self.assertEqual(len(drafter.opened), 1)
            self.assertEqual(len(planner.opened), 1)
            self.assertEqual(len(builder.opened), 1)
            self.assertEqual(len(analyst.opened), 2)
            self.assertEqual(len(reviewer.opened), 1)

    def test_plan_must_converge(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            workspace = Path(directory)
            topology = SessionTopology(
                drafter=FakeAgent([["idea draft"]]),
                planner=FakeAgent([[PLAN, PLAN]]),
                analyst=FakeAgent([["analysis"], ["DISAGREE"]]),
                builder=FakeAgent([["builder summary"]]),
                reviewer=FakeAgent([["VERDICT: ADVANCED\nBLOCKING: NONE\nSTATUS: INCOMPLETE"]]),
                cwd=workspace,
            )
            flow = HumanizeFlow(workspace)
            flow.begin("new flow")
            stages = HumanizeStages(flow, topology)
            idea = stages.gen_idea("new flow")
            with self.assertRaises(RuntimeError):
                stages.gen_plan(idea, max_convergence_rounds=1)
            self.assertEqual(flow.state.phase, Phase.PLAN)

    def test_complete_review_requires_explicit_unblocked_protocol(self) -> None:
        parsed = HumanizeStages._review_result(
            "VERDICT: ADVANCED\nBLOCKING: NONE\nSTATUS: COMPLETE"
        )
        self.assertTrue(parsed.complete)
        with self.assertRaises(ValueError):
            HumanizeStages._review_result(
                "VERDICT: STALLED\nBLOCKING: NONE\nSTATUS: COMPLETE"
            )

    def test_pending_review_can_resume_without_repeating_builder(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            workspace = Path(directory)
            builder = FakeAgent([["builder summary"]])
            reviewer = FakeAgent([["VERDICT: ADVANCED\nBLOCKING: NONE\nSTATUS: INCOMPLETE"]])
            topology = SessionTopology(
                drafter=FakeAgent([["idea"]]),
                planner=FakeAgent([[PLAN]]),
                analyst=FakeAgent([["analysis"]]),
                builder=builder,
                reviewer=reviewer,
                cwd=workspace,
            )
            flow = HumanizeFlow(workspace)
            flow.begin("new flow")
            flow.record_idea("idea")
            flow.record_plan(PLAN, goal_tracker="goal tracker")
            flow.begin_round("bounded objective")
            flow.finish_builder_round("builder summary")
            stages = HumanizeStages(flow, topology)
            result = stages.resume_review()
            self.assertEqual(result.verdict.value, "ADVANCED")
            self.assertEqual(flow.state.phase, Phase.IMPLEMENTATION)
            self.assertEqual(len(builder.opened[0].prompts), 0)


if __name__ == "__main__":
    unittest.main()
