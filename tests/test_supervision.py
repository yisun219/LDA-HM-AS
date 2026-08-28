from __future__ import annotations

import json
import tempfile
import time
import unittest
from pathlib import Path

from lda_hm import (
    BuilderWatchdog,
    FakeSandbox,
    HumanizeFlow,
    MainlineVerdict,
    ReviewResult,
    SandboxResult,
    Supervisor,
    TraceStats,
    parse_supervisor_answer,
)


def _ok(command: tuple[str, ...], stdout: str) -> SandboxResult:
    return SandboxResult(command, 0, stdout, "", 0.001, "fake-sandbox")


class SupervisorAnswerTest(unittest.TestCase):
    def test_parses_strict_protocol(self) -> None:
        decision = parse_supervisor_answer(
            "analysis text\nACTION: RETARGET\nCONTRACT: fix the abi fence\nREASON: repeated failure\n"
        )
        self.assertEqual(decision.action, "retarget")
        self.assertEqual(decision.contract, "fix the abi fence")
        self.assertEqual(decision.source, "llm")

    def test_rejects_missing_action(self) -> None:
        with self.assertRaises(ValueError):
            parse_supervisor_answer("CONTRACT: x\nREASON: y\n")

    def test_none_contract_becomes_empty(self) -> None:
        decision = parse_supervisor_answer(
            "ACTION: CONTINUE\nCONTRACT: NONE\nREASON: on track\n"
        )
        self.assertEqual(decision.contract, "")


class TraceStatsTest(unittest.TestCase):
    def test_reads_costs_and_turns(self) -> None:
        lines = [
            json.dumps({"kind": "turn_start", "role": "builder"}),
            json.dumps(
                {
                    "type": "assistant",
                    "message": {"content": [{"type": "tool_use", "name": "Bash"}]},
                }
            ),
            json.dumps(
                {
                    "type": "result",
                    "total_cost_usd": 1.25,
                    "usage": {"output_tokens": 420},
                }
            ),
            "not json",
        ]
        stats = TraceStats.from_lines(lines)
        self.assertEqual(stats.turns, 1)
        self.assertEqual(stats.tool_uses, 1)
        self.assertEqual(stats.results, 1)
        self.assertAlmostEqual(stats.total_cost_usd, 1.25)
        self.assertEqual(stats.output_tokens, 420)


class SupervisorDecisionTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.flow = HumanizeFlow(Path(self.tmp.name))
        self.flow.begin("task")
        self.flow.record_idea("idea")
        self.flow.record_plan(
            "goal\ncriterion\npositive\nnegative\nboundary",
            goal_tracker="tracker",
        )
        self.sandbox = FakeSandbox()

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def _supervisor(self, **kwargs) -> Supervisor:
        return Supervisor(
            self.flow,
            self.sandbox,
            default_contract="advance the plan",
            **kwargs,
        )

    def test_human_abort_wins(self) -> None:
        supervisor = self._supervisor()
        pulse = supervisor.pulse()
        decision = supervisor.decide(pulse, {"action": "abort", "reason": "operator said stop"})
        self.assertEqual(decision.action, "abort")
        self.assertEqual(decision.source, "human")

    def test_budget_exhaustion_aborts(self) -> None:
        supervisor = self._supervisor(budget_usd=0.0000001)
        # Spend probe returns nothing -> 0.0 spent; force by lowering budget to 0.
        supervisor.budget_usd = -1.0
        decision = supervisor.decide(supervisor.pulse(), {})
        self.assertEqual(decision.action, "abort")

    def test_repeated_fence_block_consults_with_targeted_contract(self) -> None:
        self.flow.begin_round("contract")
        self.flow.finish_builder_round("summary")
        self.flow.record_blocked_round("fence", "abi diff failed")
        self.flow.begin_round("contract")
        self.flow.finish_builder_round("summary")
        self.flow.record_blocked_round("fence", "abi diff failed again")
        supervisor = self._supervisor()
        decision = supervisor.decide(supervisor.pulse(), {})
        # Entering drift recovery adds an analyst AND carries the targeted
        # repeated-failure contract.
        self.assertEqual(decision.action, "consult_analyst")
        self.assertIn("fence", decision.contract)
        # With the consult already spent, the plain retarget rule takes over.
        self.flow.state.metadata["last_analyst_consult_round"] = (
            self.flow.state.current_round
        )
        decision = supervisor.decide(supervisor.pulse(), {})
        self.assertEqual(decision.action, "retarget")
        self.assertIn("fence", decision.contract)

    def test_llm_abort_is_demoted(self) -> None:
        class Session:
            def ask(self, prompt, *, schema=None):
                return "ACTION: ABORT\nCONTRACT: NONE\nREASON: hopeless"

        self.flow.begin_round("contract")
        self.flow.finish_builder_round("summary")
        self.flow.record_review(
            ReviewResult(verdict=MainlineVerdict.STALLED, feedback="no progress")
        )
        supervisor = self._supervisor(
            consult=lambda role: Session(), supervisor_prompt="{pulse}"
        )
        decision = supervisor.decide(supervisor.pulse(), {})
        self.assertEqual(decision.action, "retarget")
        self.assertIn("demoted", decision.reason)

    def test_malformed_llm_falls_back_to_rules(self) -> None:
        class Session:
            def ask(self, prompt, *, schema=None):
                return "I think we should keep going"

        self.flow.begin_round("contract")
        self.flow.finish_builder_round("summary")
        self.flow.record_review(
            ReviewResult(verdict=MainlineVerdict.STALLED, feedback="no progress")
        )
        supervisor = self._supervisor(
            consult=lambda role: Session(), supervisor_prompt="{pulse}"
        )
        decision = supervisor.decide(supervisor.pulse(), {})
        self.assertEqual(decision.source, "rules")
        self.assertEqual(decision.action, "continue")

    def _block(self, reason: str) -> None:
        self.flow.begin_round("contract")
        self.flow.finish_builder_round("summary")
        self.flow.record_blocked_round("benchmark", reason)

    def test_improving_near_miss_earns_one_grace(self) -> None:
        self._block(
            "benchmark speedup target not met [train] end_to_end/e2e: "
            "speedup=-0.700% required=1.000% (noise=1.1%)"
        )
        self._block(
            "benchmark speedup target not met [train] end_to_end/e2e: "
            "speedup=0.690% required=1.000% (noise=1.1%)"
        )
        supervisor = self._supervisor()
        decision = supervisor.decide(supervisor.pulse(), {})
        self.assertEqual(decision.action, "grant_grace")
        self.assertTrue(self.flow.grant_grace(decision.reason))
        self.assertEqual(self.flow.state.stall_count, 1)
        # Grace is single-use.
        self.assertFalse(self.flow.grant_grace("again"))

    def test_regression_block_gets_no_grace(self) -> None:
        self._block("benchmark regression [train] micro/m:boundary: 2.2% slower")
        self._block("benchmark regression [train] micro/m:boundary: 4.9% slower")
        supervisor = self._supervisor()
        decision = supervisor.decide(supervisor.pulse(), {})
        self.assertNotEqual(decision.action, "grant_grace")

    def test_far_miss_gets_no_grace(self) -> None:
        self._block(
            "benchmark speedup target not met [train] end_to_end/e2e: "
            "speedup=0.100% required=1.000% (noise=1.1%)"
        )
        self._block(
            "benchmark speedup target not met [train] end_to_end/e2e: "
            "speedup=0.200% required=1.000% (noise=1.1%)"
        )
        supervisor = self._supervisor()
        decision = supervisor.decide(supervisor.pulse(), {})
        self.assertNotEqual(decision.action, "grant_grace")

    def test_drift_recovery_adds_an_analyst_once(self) -> None:
        class Session:
            def ask(self, prompt, *, schema=None):
                return "Root cause: dispatch in per-image path. Route: one-time init."

        self._block("benchmark regression [train] micro/m:boundary: slow")
        self._block("benchmark regression [train] micro/m:boundary: slow again")
        self.assertEqual(self.flow.state.phase.value, "drift_recovery")
        supervisor = self._supervisor(fresh_analyst=lambda: Session())
        pulse = supervisor.pulse()
        decision = supervisor.decide(pulse, {})
        self.assertEqual(decision.action, "consult_analyst")
        diagnosis = supervisor.consult_analyst(pulse)
        self.assertIn("Root cause", diagnosis)
        path = self.flow.store.rounds / str(self.flow.state.current_round) / "diagnosis.md"
        self.assertTrue(path.is_file())
        # Same stall streak: no second consult.
        decision = supervisor.decide(supervisor.pulse(), {})
        self.assertNotEqual(decision.action, "consult_analyst")

    def test_analyst_failure_never_blocks(self) -> None:
        class DeadSession:
            def ask(self, prompt, *, schema=None):
                raise RuntimeError("backend down")

        self._block("benchmark regression [train] micro/m:boundary: slow")
        self._block("benchmark regression [train] micro/m:boundary: slow again")
        supervisor = self._supervisor(fresh_analyst=lambda: DeadSession())
        pulse = supervisor.pulse()
        self.assertEqual(supervisor.consult_analyst(pulse), "")

    def test_records_decision_artifact(self) -> None:
        supervisor = self._supervisor()
        pulse = supervisor.pulse()
        decision = supervisor.decide(pulse, {})
        supervisor.record(pulse, decision)
        path = self.flow.store.rounds / "0" / "supervision.json"
        value = json.loads(path.read_text(encoding="utf-8"))
        self.assertEqual(value["decision"]["action"], "continue")
        self.assertIn("pulse", value)


class InfraBlockTest(unittest.TestCase):
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

    def _blocked_round(self, *, infra: bool) -> None:
        self.flow.begin_round("contract")
        self.flow.finish_builder_round("summary")
        self.flow.record_blocked_round("benchmark-environment", "steal too high", infra=infra)

    def test_infra_blocks_do_not_feed_stall_counter(self) -> None:
        self._blocked_round(infra=True)
        self._blocked_round(infra=True)
        self.assertEqual(self.flow.state.stall_count, 0)
        self.assertEqual(self.flow.state.phase.value, "implementation")

    def test_three_consecutive_infra_blocks_stop_the_run(self) -> None:
        self._blocked_round(infra=True)
        self._blocked_round(infra=True)
        self._blocked_round(infra=True)
        self.assertEqual(self.flow.state.phase.value, "stop")

    def test_candidate_blocks_still_drift(self) -> None:
        self._blocked_round(infra=False)
        self._blocked_round(infra=False)
        self.assertEqual(self.flow.state.stall_count, 2)
        self.assertEqual(self.flow.state.phase.value, "drift_recovery")


class WatchdogTest(unittest.TestCase):
    def test_kills_after_confirmed_stall(self) -> None:
        class StaticSandbox(FakeSandbox):
            def __init__(self):
                super().__init__()
                self.killed = False

            def run(self, command, *, timeout_seconds=900, envs=None):
                if "pkill" in " ".join(command):
                    self.killed = True
                if "du -sb" in " ".join(command):
                    return _ok(tuple(command), "1000\n")
                return super().run(command, timeout_seconds=timeout_seconds, envs=envs)

        sandbox = StaticSandbox()
        with BuilderWatchdog(
            sandbox, stall_seconds=1, poll_seconds=0.05
        ) as watchdog:
            time.sleep(2.0)
        self.assertTrue(watchdog.killed)
        self.assertTrue(sandbox.killed)

    def test_growing_activity_is_not_killed(self) -> None:
        class GrowingSandbox(FakeSandbox):
            def __init__(self):
                super().__init__()
                self.size = 0
                self.killed = False

            def run(self, command, *, timeout_seconds=900, envs=None):
                joined = " ".join(command)
                if "pkill" in joined:
                    self.killed = True
                if "du -sb" in joined:
                    self.size += 100
                    return _ok(tuple(command), f"{self.size}\n")
                return super().run(command, timeout_seconds=timeout_seconds, envs=envs)

        sandbox = GrowingSandbox()
        with BuilderWatchdog(
            sandbox, stall_seconds=1, poll_seconds=0.05
        ) as watchdog:
            time.sleep(0.6)
        self.assertFalse(watchdog.killed)
        self.assertFalse(sandbox.killed)

    def test_blind_watchdog_never_kills(self) -> None:
        class BlindSandbox(FakeSandbox):
            def __init__(self):
                super().__init__()
                self.killed = False

            def run(self, command, *, timeout_seconds=900, envs=None):
                joined = " ".join(command)
                if "pkill" in joined:
                    self.killed = True
                if "du -sb" in joined:
                    return SandboxResult(tuple(command), 1, "", "denied", 0.001, "fake")
                return super().run(command, timeout_seconds=timeout_seconds, envs=envs)

        sandbox = BlindSandbox()
        with BuilderWatchdog(
            sandbox, stall_seconds=0.1, poll_seconds=0.02
        ) as watchdog:
            time.sleep(0.4)
        self.assertFalse(watchdog.killed)
        self.assertFalse(sandbox.killed)


if __name__ == "__main__":
    unittest.main()
