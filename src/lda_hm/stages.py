from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from .flow import HumanizeFlow
from .prompts import (
    CODE_REVIEW,
    DRIFT_RECOVERY,
    FULL_ALIGNMENT,
    GEN_IDEA,
    GEN_PLAN,
    GEN_PLAN_ANALYSIS,
    REGULAR_REVIEW,
)
from .runtime import SessionTopology
from .types import MainlineVerdict, ReviewResult


@dataclass(frozen=True)
class PlanAnalysis:
    relevant: bool
    text: str


class HumanizeStages:
    """Agent-facing stage entry points; no concrete backend is assumed."""

    def __init__(self, flow: HumanizeFlow, topology: SessionTopology) -> None:
        self.flow = flow
        self.topology = topology

    def gen_idea(self, task: str, *, directions: int = 6) -> str:
        if not 2 <= directions <= 10:
            raise ValueError("directions must be between 2 and 10")
        answer = self.topology.drafter.ask(
            GEN_IDEA.format(task=task, directions=directions)
        )
        draft = self._text(answer, "drafter returned an empty idea")
        self.flow.record_idea(draft)
        return draft

    def gen_plan(self, idea: str) -> str:
        analysis_answer = self.topology.fresh_analyst().ask(
            GEN_PLAN_ANALYSIS.format(idea=idea)
        )
        analysis = self._text(analysis_answer, "analyst returned an empty analysis")
        candidate = self.topology.planner.ask(
            GEN_PLAN.format(idea=idea, analysis=analysis)
        )
        plan = self._text(candidate, "planner returned an empty plan")
        self.flow.record_plan(plan, goal_tracker=self._goal_tracker(plan))
        return plan

    def review_round(self, *, summary: str, contract: str) -> ReviewResult:
        self.flow.begin_round(contract)
        builder_answer = self.topology.builder.ask(contract)
        builder_text = self._text(builder_answer, "builder returned an empty answer")
        phase = self.flow.finish_builder_round(builder_text)
        if phase.value == "full_alignment":
            prompt = FULL_ALIGNMENT.format(round=self.flow.state.current_round)
        elif phase.value == "drift_recovery":
            prompt = DRIFT_RECOVERY
        else:
            prompt = REGULAR_REVIEW.format(round=self.flow.state.current_round)
        review_answer = self.topology.fresh_reviewer().ask(prompt)
        result = self._review_result(review_answer)
        self.flow.record_review(result)
        return result

    def code_review(self) -> tuple[str, ...]:
        answer = self.topology.fresh_reviewer().ask(CODE_REVIEW)
        text = self._text(answer, "reviewer returned an empty code review")
        findings = tuple(
            line.strip() for line in text.splitlines() if line.lstrip().startswith("[P")
        )
        self.flow.record_code_review(findings)
        return findings

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
        verdict = next(
            (MainlineVerdict(value) for value in ("ADVANCED", "STALLED", "REGRESSED")
             if any(line == value for line in lines)),
            None,
        )
        if verdict is None:
            raise ValueError("reviewer must return ADVANCED, STALLED, or REGRESSED")
        complete = lines[-1] == "COMPLETE" if lines else False
        return ReviewResult(verdict=verdict, complete=complete, feedback=text)
