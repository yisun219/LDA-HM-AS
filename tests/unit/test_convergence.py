from lda.controller.convergence import ConvergenceEvaluator, ConvergenceReason
from lda.models import CandidateState, CandidateStatus, MissionState


def test_candidate_convergence_is_deterministic() -> None:
    evaluator = ConvergenceEvaluator(max_attempts=8, stagnation_rounds=3)
    state = CandidateState(candidate_id="c", mission_id="m", attempts=8)
    assert evaluator.candidate(state) is ConvergenceReason.ATTEMPT_LIMIT
    state.attempts = 2
    state.no_improvement_rounds = 3
    assert evaluator.candidate(state) is ConvergenceReason.STAGNATED
    state.status = CandidateStatus.LOCAL_WIN
    assert evaluator.candidate(state) is ConvergenceReason.JUDGE_PASSED


def test_mission_converges_after_a_win() -> None:
    evaluator = ConvergenceEvaluator()
    mission = MissionState(mission_id="m", candidates={"c": CandidateState(candidate_id="c", mission_id="m", status=CandidateStatus.SYSTEM_WIN)})
    assert evaluator.mission(mission) is ConvergenceReason.JUDGE_PASSED
