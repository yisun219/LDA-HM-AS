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
            reviewer = FakeAgent([["Mainline Progress Verdict: ADVANCED"]])
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


if __name__ == "__main__":
    unittest.main()
