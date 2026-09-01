"""Infrastructure failures are evidence about the environment, never verdicts.

Three regressions seen in production runs, pinned here:
- a Builder turn killed by a model-gateway failure was judged as a candidate
  round (benchmarks ran on a half-finished worktree, the stall counter grew,
  the run circuit-broke on an outage);
- a Reviewer that restated the protocol while reasoning was rejected for
  "more than one VERDICT line";
- the trace audit matched forbidden verbs inside prose and, because the
  trace is cumulative, failed every later round of the session.
"""
from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from lda_hm import HumanizeFlow, HumanizeStages, Phase
from lda_hm.runtime import SessionTopology
from lda_hm.stages import api_error_marker

AUDIT = Path(__file__).resolve().parents[1] / "sandbox" / "lda-base" / "harness" / "audit_trace.py"

PLAN = """# Candidate Plan
Goal: preserve alignment.
Positive test: required behavior passes.
Negative test: forbidden behavior fails.
Path boundary: only declared files.
Task: one bounded implementation step.
"""


class FailingSession:
    def __init__(self, error: Exception) -> None:
        self.error = error
        self.prompts: list[str] = []

    def ask(self, prompt: str, *, schema=None):
        self.prompts.append(prompt)
        raise self.error


class TextSession:
    def __init__(self, text: str) -> None:
        self.text = text
        self.prompts: list[str] = []

    def ask(self, prompt: str, *, schema=None):
        self.prompts.append(prompt)
        return self.text


class OneAgent:
    def __init__(self, session) -> None:
        self.session = session
        self.opened = 0

    def new_session(self, cwd: Path):
        self.opened += 1
        return self.session


class NeverAgent:
    def new_session(self, cwd: Path):
        raise AssertionError("this role must not be consulted")


def _flow_in_implementation(workspace: Path) -> HumanizeFlow:
    flow = HumanizeFlow(workspace)
    flow.begin("task")
    flow.record_idea("idea")
    flow.record_plan(PLAN, goal_tracker="tracker")
    return flow


class BuilderInfraTest(unittest.TestCase):
    def _topology(self, builder_session, workspace: Path) -> SessionTopology:
        return SessionTopology(
            drafter=OneAgent(TextSession("idea")),
            planner=OneAgent(TextSession(PLAN)),
            analyst=OneAgent(TextSession("analysis")),
            builder=OneAgent(builder_session),
            reviewer=NeverAgent(),
            cwd=workspace,
        )

    def test_dead_builder_turn_is_an_infra_block_without_benchmarks(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            workspace = Path(directory)
            flow = _flow_in_implementation(workspace)
            hooks = {"benchmarks": 0}

            def pre_review():
                hooks["benchmarks"] += 1

            stages = HumanizeStages(
                flow,
                self._topology(FailingSession(RuntimeError("agent turn failed: exit 125")), workspace),
                pre_review_hook=pre_review,
            )
            result = stages.review_round(contract="advance")
            self.assertEqual(hooks["benchmarks"], 0, "no benchmark may judge an interrupted turn")
            self.assertEqual(flow.state.stall_count, 0)
            self.assertEqual(flow.state.phase, Phase.IMPLEMENTATION)
            blocked = json.loads((flow.store.rounds / "0" / "blocked.json").read_text())
            self.assertEqual(blocked["source"], "builder-infra")
            self.assertTrue(blocked["infra"])
            self.assertIn("BUILDER_TURN_FAILED", result.feedback)

    def test_api_error_answer_is_an_infra_block(self) -> None:
        text = (
            "API Error: 502 {\"cloudflare_error\":true,\"retryable\":true} "
            "This is a server-side issue, usually temporary"
        )
        with tempfile.TemporaryDirectory() as directory:
            workspace = Path(directory)
            flow = _flow_in_implementation(workspace)
            stages = HumanizeStages(flow, self._topology(TextSession(text), workspace))
            stages.review_round(contract="advance")
            blocked = json.loads((flow.store.rounds / "0" / "blocked.json").read_text())
            self.assertEqual(blocked["source"], "builder-infra")
            self.assertEqual(flow.state.stall_count, 0)

    def test_next_contract_explains_the_interruption(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            workspace = Path(directory)
            flow = _flow_in_implementation(workspace)
            first = FailingSession(RuntimeError("agent turn failed"))
            stages = HumanizeStages(flow, self._topology(first, workspace))
            stages.review_round(contract="advance")
            second = TextSession("API Error: 529 overloaded")
            stages = HumanizeStages(flow, self._topology(second, workspace))
            stages.review_round(contract="advance")
            self.assertIn("interrupted by an infrastructure failure", second.prompts[0])
            self.assertIn("git status", second.prompts[0])


class ApiErrorMarkerTest(unittest.TestCase):
    def test_markers(self) -> None:
        self.assertTrue(api_error_marker("API Error: 502 bad gateway"))
        self.assertTrue(api_error_marker("x\n{\"cloudflare_error\": true}"))
        self.assertTrue(api_error_marker("Opus 4.8's safeguards flagged this message. Details: `[cyber]`"))
        self.assertEqual(api_error_marker("Changed files: a.c; commit abc; API errors were not seen"), "")


class ReviewProtocolTest(unittest.TestCase):
    def test_closing_block_wins_over_a_restated_protocol(self) -> None:
        answer = (
            "The protocol asks for VERDICT: ADVANCED|STALLED|REGRESSED lines, "
            "then BLOCKING: and STATUS:.\n"
            "Evidence: the holdout cleared 1%.\n"
            "VERDICT: ADVANCED\nBLOCKING: NONE\nSTATUS: INCOMPLETE\n"
        )
        parsed = HumanizeStages._review_result(answer)
        self.assertEqual(parsed.verdict.value, "ADVANCED")
        self.assertFalse(parsed.complete)

    def test_api_error_is_not_a_verdict(self) -> None:
        with self.assertRaises(RuntimeError):
            HumanizeStages._review_result("API Error: 502 {\"cloudflare_error\":true}")

    def test_missing_verdict_still_rejected(self) -> None:
        with self.assertRaises(ValueError):
            HumanizeStages._review_result("BLOCKING: NONE\nSTATUS: INCOMPLETE")


class TraceAuditTest(unittest.TestCase):
    def _audit(self, events) -> subprocess.CompletedProcess:
        with tempfile.NamedTemporaryFile("w", suffix=".jsonl", delete=False) as handle:
            handle.write(json.dumps({"kind": "turn_start", "role": "builder"}) + "\n")
            for event in events:
                handle.write(json.dumps(event) + "\n")
            path = handle.name
        return subprocess.run([sys.executable, str(AUDIT), path], capture_output=True, text=True)

    @staticmethod
    def _assistant(*blocks) -> dict:
        return {"type": "assistant", "message": {"content": list(blocks)}}

    def test_prose_mentioning_forbidden_verbs_passes(self) -> None:
        result = self._audit([
            self._assistant(
                {"type": "thinking", "thinking": "I must never rm -rf the evidence or task-card files; perform a read-only check"},
                {"type": "text", "text": "Prior block: rm  evidence forbidden pattern quoted: (?:rm|truncate)\\s+.*evidence"},
            ),
            {"type": "user", "message": {"content": [{"type": "tool_result", "content": "rm -rf /opt/lda/control (from a cat of some doc)"}]}},
            {"type": "result", "result": "done; never touched /opt/lda/control"},
        ])
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_forbidden_command_fails(self) -> None:
        result = self._audit([
            self._assistant({"type": "tool_use", "name": "Bash", "input": {"command": "rm -rf /opt/lda/control/plan.md"}}),
        ])
        self.assertEqual(result.returncode, 3, result.stderr)
        self.assertIn("forbidden action", result.stderr)

    def test_read_only_search_for_forbidden_text_passes(self) -> None:
        command = (
            "/bin/bash -lc \"sed -n '1,80p' "
            "/opt/lda/harness/checks/build-package.sh; "
            "rg -n \\\"candidate|mkdir|rm -rf|build-package\\\" "
            "/opt/lda/harness/checks/build-package.sh\""
        )
        result = self._audit([
            {"type": "item.started", "item": {"type": "command_execution", "command": command}},
        ])
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_forbidden_edit_path_fails(self) -> None:
        result = self._audit([
            self._assistant({"type": "tool_use", "name": "Bash", "input": {"command": "sed -i s/x/y/ /opt/lda/control/task-card.json"}}),
        ])
        self.assertEqual(result.returncode, 3, result.stderr)

    def test_codex_command_items_are_audited(self) -> None:
        result = self._audit([
            {"type": "item.completed", "item": {"type": "command_execution", "command": "cat /tmp/lda-holdout-x/seed"}},
        ])
        self.assertEqual(result.returncode, 3, result.stderr)

    def test_holdout_peeking_fails(self) -> None:
        result = self._audit([
            self._assistant({"type": "tool_use", "name": "Bash", "input": {"command": "ls /tmp/lda-holdout-run-r3"}}),
        ])
        self.assertEqual(result.returncode, 3, result.stderr)


if __name__ == "__main__":
    unittest.main()
