from __future__ import annotations

import json
from dataclasses import dataclass

from .benchmark import BenchmarkEnvironmentError
from .flow import HumanizeFlow
from .fence import FenceResult, FenceSuite, parse_p_severity
from .gates import GateContext, GateRunner
from .prompts import (
    BUILDER_ROUND,
    CODE_REVIEW,
    DRIFT_RECOVERY,
    FULL_ALIGNMENT,
    GEN_IDEA,
    GEN_PLAN,
    GEN_PLAN_ANALYSIS,
    GEN_PLAN_REVIEW,
    GEN_PLAN_REVISE,
    METHODOLOGY_ANALYSIS,
    REGULAR_REVIEW,
)
from .runtime import SessionTopology
from .types import MainlineVerdict, Phase, ReviewResult


@dataclass(frozen=True)
class PlanAnalysis:
    relevant: bool
    text: str


class FenceBlocked(RuntimeError):
    """The Reviewer is not allowed to judge a round that failed a fence."""


class GateBlocked(RuntimeError):
    """The Reviewer is not allowed to judge a round that failed a gate."""


class HumanizeStages:
    """Agent-facing stage entry points; no concrete backend is assumed."""

    def __init__(
        self,
        flow: HumanizeFlow,
        topology: SessionTopology,
        *,
        fence_suite: FenceSuite | None = None,
        gate_runner: GateRunner | None = None,
        gate_context_factory=None,
        pre_review_hook=None,
        builder_guard=None,
        certifier=None,
    ) -> None:
        self.flow = flow
        self.topology = topology
        self.fence_suite = fence_suite
        self.gate_runner = gate_runner
        self.gate_context_factory = gate_context_factory
        self.pre_review_hook = pre_review_hook
        # Optional context-manager factory that supervises one Builder turn
        # (e.g. a live trace watchdog) while the turn is running.
        self.builder_guard = builder_guard
        # Optional fresh-environment certification; returns None on success
        # or a human-readable failure reason.
        self.certifier = certifier

    def gen_idea(self, task: str, *, directions: int = 6) -> str:
        if not 2 <= directions <= 10:
            raise ValueError("directions must be between 2 and 10")
        answer = self.topology.drafter.ask(
            GEN_IDEA.format(task=task, directions=directions)
        )
        draft = self._text(answer, "drafter returned an empty idea")
        self.flow.record_idea(draft)
        return draft

    def gen_plan(self, idea: str, *, max_convergence_rounds: int = 3) -> str:
        if not 1 <= max_convergence_rounds <= 10:
            raise ValueError("max_convergence_rounds must be between 1 and 10")
        analysis_answer = self.topology.fresh_analyst().ask(
            GEN_PLAN_ANALYSIS.format(idea=idea)
        )
        analysis = self._text(analysis_answer, "analyst returned an empty analysis")
        self.flow.store.write_text("planning/analysis.md", analysis + "\n")
        candidate = self.topology.planner.ask(
            GEN_PLAN.format(idea=idea, analysis=analysis)
        )
        plan = self._text(candidate, "planner returned an empty plan")
        self.flow.store.write_text("planning/candidate-0.md", plan + "\n")
        converged = False
        for round_number in range(max_convergence_rounds):
            review_answer = self.topology.fresh_analyst().ask(
                GEN_PLAN_REVIEW.format(idea=idea, plan=plan)
            )
            review = self._text(review_answer, "analyst returned an empty plan review")
            self.flow.store.write_text(
                f"planning/review-{round_number}.md", review + "\n"
            )
            if review.splitlines()[-1].strip() == "CONVERGED":
                converged = True
                break
            revised = self.topology.planner.ask(GEN_PLAN_REVISE.format(review=review))
            plan = self._text(revised, "planner returned an empty revision")
            self.flow.store.write_text(
                f"planning/candidate-{round_number + 1}.md", plan + "\n"
            )
        if not converged:
            # Autonomy over analyst perfectionism: proceed with the last
            # candidate, record the outstanding objections durably, and let
            # the review/drift machinery judge the plan by its results.
            self.flow.store.write_json(
                "planning/non-convergence.json",
                {
                    "max_convergence_rounds": max_convergence_rounds,
                    "note": "proceeded with the final candidate plan",
                },
            )
        self.flow.record_plan(plan, goal_tracker=self._goal_tracker(plan))
        return plan

    def review_round(self, *, contract: str) -> ReviewResult:
        recovering = self.flow.state.drift_recovery_required
        self.flow.begin_round(contract)
        prior_feedback = self._prior_feedback()
        effective_contract = contract
        if prior_feedback:
            effective_contract += "\n\nPrior blocking feedback:\n" + prior_feedback
        builder_prompt = (
            f"{DRIFT_RECOVERY}\n\n{BUILDER_ROUND.format(contract=effective_contract)}"
            if recovering
            else BUILDER_ROUND.format(contract=effective_contract)
        )
        guard = self.builder_guard() if self.builder_guard is not None else None
        try:
            if guard is not None:
                with guard:
                    builder_answer = self.topology.builder.ask(builder_prompt)
            else:
                builder_answer = self.topology.builder.ask(builder_prompt)
            builder_text = self._text(builder_answer, "builder returned an empty answer")
        except (RuntimeError, ValueError) as error:
            # A dead or killed Builder turn is a judged failure, not a crash:
            # the fences and gates now rule on whatever state the turn left.
            detail = ""
            if guard is not None and getattr(guard, "killed", False):
                detail = " (watchdog killed a stalled agent process)"
            builder_text = f"BUILDER_TURN_FAILED{detail}: {error}"
        phase = self.flow.finish_builder_round(builder_text)
        return self._evaluate_review(phase)

    def resume_review(self) -> ReviewResult:
        if self.flow.state.phase not in {Phase.REGULAR_REVIEW, Phase.FULL_ALIGNMENT}:
            raise ValueError("no pending review is available to resume")
        return self._evaluate_review(self.flow.state.phase)

    def _evaluate_review(self, phase: Phase) -> ReviewResult:
        if self.pre_review_hook is not None:
            try:
                self.pre_review_hook()
            except BenchmarkEnvironmentError as error:
                return self._blocked("benchmark-environment", str(error), infra=True)
            except Exception as error:
                return self._blocked("benchmark", str(error))
        if self.fence_suite is not None:
            fence_results = self.fence_suite.run()
            self.flow.store.write_json(
                self.flow.store.round_dir(self.flow.state.current_round).relative_to(self.flow.store.root)
                / "fence.json",
                {
                    "results": [
                        {
                            "name": result.name,
                            "passed": result.passed,
                            "reason": result.reason,
                        }
                        for result in fence_results
                    ]
                },
            )
            if not all(result.passed for result in fence_results):
                failed = [result for result in fence_results if not result.passed]
                # Transport death (E2B exit 125) is evidence about the
                # sandbox, never about the candidate.
                transport = all(
                    any(
                        command.exit_code == 125
                        for command in result.command_results
                    )
                    for result in failed
                    if result.command_results
                ) and any(result.command_results for result in failed)
                return self._blocked(
                    "sandbox-transport" if transport else "fence",
                    "; ".join(result.reason for result in failed),
                    infra=transport,
                )
        if self.gate_runner is not None:
            if self.gate_context_factory is None:
                raise ValueError("gate_context_factory is required with gate_runner")
            context: GateContext = self.gate_context_factory(self.flow)
            gate_results = self.gate_runner.run(context)
            self.flow.store.write_json(
                self.flow.store.round_dir(self.flow.state.current_round).relative_to(self.flow.store.root)
                / "gates.json",
                {
                    "results": [
                        {
                            "name": result.name,
                            "passed": result.passed,
                            "reason": result.reason,
                            "terminal_phase": result.terminal_phase.value if result.terminal_phase else None,
                        }
                        for result in gate_results
                    ]
                },
            )
            if not all(result.passed for result in gate_results):
                return self._blocked(
                    "gate",
                    "; ".join(
                        result.reason for result in gate_results if not result.passed
                    ),
                )
        if phase is Phase.FULL_ALIGNMENT:
            prompt = FULL_ALIGNMENT.format(round=self.flow.state.current_round)
        else:
            prompt = REGULAR_REVIEW.format(round=self.flow.state.current_round)
        result = None
        last_error: Exception | None = None
        for _ in range(2):
            # A malformed verdict earns one fresh re-review (humanize's
            # missing-verdict rerun); persistent malformation is an
            # infrastructure block, not a candidate judgement.
            try:
                review_answer = self.topology.fresh_reviewer().ask(prompt)
                result = self._review_result(review_answer)
                break
            except (RuntimeError, ValueError) as error:
                last_error = error
        if result is None:
            return self._blocked(
                "reviewer-infra", f"reviewer produced no valid verdict: {last_error}",
                infra=True,
            )
        self.flow.record_review(result)
        return result

    def _blocked(self, source: str, reason: str, *, infra: bool = False) -> ReviewResult:
        feedback = f"DETERMINISTIC_{source.upper().replace('-', '_')}_BLOCK: {reason}"
        self.flow.record_blocked_round(source, reason, infra=infra)
        return ReviewResult(
            verdict=MainlineVerdict.REGRESSED,
            complete=False,
            feedback=feedback,
            blocking_findings=(feedback,),
        )

    def _prior_feedback(self) -> str:
        if self.flow.state.current_round == 0:
            return ""
        previous_round = self.flow.state.current_round - 1
        # A finalize reopen (failed certification) or code-review findings
        # re-enter implementation from root-level artifacts, not from the
        # prior round directory; without this the Builder never learns why.
        for name, render in (
            (
                "finalize-blocked.json",
                lambda value: f"finalize reopened: {value.get('reason', '')}",
            ),
            (
                "code-review.json",
                lambda value: "code review findings: "
                + "; ".join(value.get("findings") or ())
                if value.get("findings")
                else "",
            ),
        ):
            path = self.flow.store.root / name
            if not path.is_file():
                continue
            try:
                value = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            if value.get("round") == previous_round:
                rendered = render(value)
                if rendered:
                    return rendered
        prior = self.flow.store.round_dir(previous_round)
        for name in ("blocked.json", "review.json"):
            path = prior / name
            if not path.is_file():
                continue
            value = json.loads(path.read_text(encoding="utf-8"))
            if name == "blocked.json":
                return f"{value.get('source', 'unknown')}: {value.get('reason', '')}"
            return str(value.get("feedback", ""))
        return ""

    def code_review(self) -> tuple[str, ...]:
        answer = self.topology.fresh_reviewer().ask(CODE_REVIEW)
        text = self._text(answer, "reviewer returned an empty code review")
        findings = parse_p_severity(text.splitlines())
        self.flow.record_code_review(findings)
        return findings

    def finalize(self) -> str:
        if self.fence_suite is None:
            raise ValueError("finalize requires deterministic fences")
        results = self.fence_suite.run()
        failures = [result.reason for result in results if not result.passed]
        if failures:
            reason = "; ".join(failures)
            self.flow.reopen_from_finalize(reason)
            return reason
        certification_note = "certification: not configured"
        if self.certifier is not None:
            reason = self.certifier()
            if reason:
                reason = f"fresh-sandbox certification failed: {reason}"
                self.flow.reopen_from_finalize(reason)
                return reason
            certification_note = "certification: passed in fresh sandboxes"
        sandbox = self.fence_suite.sandbox
        commit = sandbox.run(("git", "-C", "/opt/lda/work", "rev-parse", "HEAD"))
        package = sandbox.run(("cat", "/opt/lda/candidate/runtime-deb.sha256"))
        if not commit.ok or not package.ok:
            reason = "final candidate identity is unavailable"
            self.flow.reopen_from_finalize(reason)
            return reason
        summary = (
            "Final deterministic fences passed.\n\n"
            f"{certification_note}\n\n"
            f"Git commit: {commit.stdout.strip()}\n\n"
            f"Candidate package: {package.stdout.strip()}"
        )
        self.flow.record_finalize(summary)
        return summary

    def methodology_analysis(self) -> str:
        answer = self.topology.fresh_analyst().ask(METHODOLOGY_ANALYSIS)
        report = self._text(answer, "analyst returned an empty methodology report")
        self.flow.record_methodology(report)
        return report

    @staticmethod
    def _text(answer: object, error: str) -> str:
        text = answer if isinstance(answer, str) else str(answer)
        if not text.strip():
            raise ValueError(error)
        return text.strip()

    @staticmethod
    def _goal_tracker(plan: str) -> str:
        return "Ultimate Goal\n\nAcceptance Criteria\n\nActive Tasks\n\n" + plan

    @staticmethod
    def _review_result(answer: object) -> ReviewResult:
        text = answer if isinstance(answer, str) else str(answer)
        lines = [line.strip() for line in text.splitlines() if line.strip()]
        verdict_lines = [line for line in lines if line.startswith("VERDICT:")]
        status_lines = [line for line in lines if line.startswith("STATUS:")]
        blocking_lines = [line for line in lines if line.startswith("BLOCKING:")]
        if len(verdict_lines) != 1:
            raise ValueError("reviewer must return exactly one VERDICT line")
        if len(status_lines) != 1:
            raise ValueError("reviewer must return exactly one STATUS line")
        if not blocking_lines:
            raise ValueError("reviewer must return at least one BLOCKING line")
        try:
            verdict = MainlineVerdict(verdict_lines[0].partition(":")[2].strip())
        except ValueError as error:
            raise ValueError("reviewer verdict must be ADVANCED, STALLED, or REGRESSED") from error
        status = status_lines[0].partition(":")[2].strip()
        if status not in {"COMPLETE", "INCOMPLETE"}:
            raise ValueError("reviewer status must be COMPLETE or INCOMPLETE")
        blocking_values = [line.partition(":")[2].strip() for line in blocking_lines]
        if "NONE" in blocking_values and len(blocking_values) != 1:
            raise ValueError("BLOCKING: NONE cannot be combined with findings")
        findings = () if blocking_values == ["NONE"] else tuple(blocking_values)
        complete = status == "COMPLETE"
        if complete and (verdict is not MainlineVerdict.ADVANCED or findings):
            raise ValueError("COMPLETE requires ADVANCED and BLOCKING: NONE")
        return ReviewResult(
            verdict=verdict,
            complete=complete,
            feedback=text,
            blocking_findings=findings,
        )
