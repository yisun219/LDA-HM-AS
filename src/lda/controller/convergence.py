from __future__ import annotations

from enum import StrEnum

from lda.models import CandidateState, CandidateStatus, MissionState


class ConvergenceReason(StrEnum):
    JUDGE_PASSED = "judge_passed"
    ATTEMPT_LIMIT = "attempt_limit"
    STAGNATED = "stagnated"
    BUDGET_EXHAUSTED = "budget_exhausted"
    ALL_FAILED = "all_failed"
    PROFILE_NOT_HOT = "profile_not_hot"
    CONTINUE = "continue"


class ConvergenceEvaluator:
    def __init__(self, *, max_attempts: int = 8, stagnation_rounds: int = 3) -> None:
        self.max_attempts = max_attempts
        self.stagnation_rounds = stagnation_rounds

    def candidate(self, state: CandidateState, *, budget_exhausted: bool = False) -> ConvergenceReason:
        if state.status in {CandidateStatus.LOCAL_WIN, CandidateStatus.SYSTEM_WIN}:
            return ConvergenceReason.JUDGE_PASSED
        if state.attempts >= self.max_attempts:
            return ConvergenceReason.ATTEMPT_LIMIT
        if state.no_improvement_rounds >= self.stagnation_rounds:
            return ConvergenceReason.STAGNATED
        if budget_exhausted:
            return ConvergenceReason.BUDGET_EXHAUSTED
        return ConvergenceReason.CONTINUE

    def mission(self, state: MissionState, *, budget_exhausted: bool = False, profile_hot: bool = True) -> ConvergenceReason:
        if not profile_hot:
            return ConvergenceReason.PROFILE_NOT_HOT
        if any(
            candidate.status in {CandidateStatus.LOCAL_WIN, CandidateStatus.SYSTEM_WIN}
            for candidate in state.candidates.values()
        ):
            return ConvergenceReason.JUDGE_PASSED
        if state.candidates and all(self.candidate(candidate, budget_exhausted=budget_exhausted) is not ConvergenceReason.CONTINUE for candidate in state.candidates.values()):
            return ConvergenceReason.ALL_FAILED
        if budget_exhausted:
            return ConvergenceReason.BUDGET_EXHAUSTED
        return ConvergenceReason.CONTINUE
