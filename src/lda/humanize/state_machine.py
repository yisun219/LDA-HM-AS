from __future__ import annotations

from lda.models import MissionPhase, MissionState, RunPhase, RunState


class InvalidFlowTransition(RuntimeError):
    pass


class PureHumanizeStateMachine:
    ALLOWED = {
        RunPhase.RUN_CREATED: {RunPhase.E2B_PREFLIGHT, RunPhase.CANCELLED, RunPhase.FAILED},
        RunPhase.E2B_PREFLIGHT: {RunPhase.RESEARCH_FROZEN, RunPhase.CANCELLED, RunPhase.FAILED},
        RunPhase.RESEARCH_FROZEN: {RunPhase.PORTFOLIO_PLANNED, RunPhase.CANCELLED, RunPhase.FAILED},
        RunPhase.PORTFOLIO_PLANNED: {RunPhase.MISSION_QUEUE_FROZEN, RunPhase.CANCELLED, RunPhase.FAILED},
        RunPhase.MISSION_QUEUE_FROZEN: {RunPhase.MISSION_BASELINE, RunPhase.PORTFOLIO_E2E, RunPhase.CANCELLED, RunPhase.FAILED},
        RunPhase.MISSION_BASELINE: {RunPhase.PROFILE, RunPhase.NEXT_MISSION, RunPhase.CANCELLED, RunPhase.FAILED},
        RunPhase.PROFILE: {RunPhase.HYPOTHESIS, RunPhase.NEXT_MISSION, RunPhase.CANCELLED, RunPhase.FAILED},
        RunPhase.HYPOTHESIS: {RunPhase.CANDIDATE_FORK, RunPhase.NEXT_MISSION, RunPhase.CANCELLED, RunPhase.FAILED},
        RunPhase.CANDIDATE_FORK: {RunPhase.BUILD, RunPhase.NEXT_MISSION, RunPhase.CANCELLED, RunPhase.FAILED},
        RunPhase.BUILD: {RunPhase.LOCAL_VERIFY, RunPhase.BUILD, RunPhase.NEXT_MISSION, RunPhase.CANCELLED, RunPhase.FAILED},
        RunPhase.LOCAL_VERIFY: {RunPhase.BUILD, RunPhase.ADVERSARIAL_REVIEW, RunPhase.NEXT_MISSION, RunPhase.CANCELLED, RunPhase.FAILED},
        RunPhase.ADVERSARIAL_REVIEW: {RunPhase.BUILD, RunPhase.CLEAN_JUDGE, RunPhase.NEXT_MISSION, RunPhase.CANCELLED, RunPhase.FAILED},
        RunPhase.CLEAN_JUDGE: {RunPhase.BUILD, RunPhase.NEXT_MISSION, RunPhase.CANCELLED, RunPhase.FAILED},
        RunPhase.NEXT_MISSION: {RunPhase.MISSION_BASELINE, RunPhase.PORTFOLIO_E2E, RunPhase.CANCELLED, RunPhase.FAILED},
        RunPhase.PORTFOLIO_E2E: {RunPhase.RELEASE_READY, RunPhase.COMPLETED_WITHOUT_RELEASE, RunPhase.CANCELLED, RunPhase.FAILED},
        RunPhase.RELEASE_READY: set(),
        RunPhase.COMPLETED_WITHOUT_RELEASE: set(),
        RunPhase.CANCELLED: set(),
        RunPhase.FAILED: set(),
    }

    @classmethod
    def transition(cls, state: RunState, target: RunPhase) -> None:
        if target is state.phase:
            return
        if target not in cls.ALLOWED[state.phase]:
            raise InvalidFlowTransition(f"run transition {state.phase} -> {target} is not allowed")
        state.phase = target


class LDAMissionStateMachine:
    ALLOWED = {
        MissionPhase.QUEUED: {MissionPhase.BASELINE, MissionPhase.INVALID},
        MissionPhase.BASELINE: {MissionPhase.PROFILE, MissionPhase.INVALID},
        MissionPhase.PROFILE: {MissionPhase.HYPOTHESIS, MissionPhase.NOT_HOT, MissionPhase.INVALID},
        MissionPhase.HYPOTHESIS: {MissionPhase.CANDIDATES, MissionPhase.INVALID},
        MissionPhase.CANDIDATES: {MissionPhase.JUDGING, MissionPhase.LOCAL_WIN, MissionPhase.SYSTEM_WIN, MissionPhase.REJECTED, MissionPhase.INVALID},
        MissionPhase.JUDGING: {MissionPhase.CANDIDATES, MissionPhase.LOCAL_WIN, MissionPhase.SYSTEM_WIN, MissionPhase.REJECTED, MissionPhase.INVALID},
        MissionPhase.LOCAL_WIN: set(),
        MissionPhase.SYSTEM_WIN: set(),
        MissionPhase.REJECTED: set(),
        MissionPhase.INVALID: set(),
        MissionPhase.NOT_HOT: set(),
    }

    @classmethod
    def transition(cls, state: MissionState, target: MissionPhase) -> None:
        if target is state.phase:
            return
        if target not in cls.ALLOWED[state.phase]:
            raise InvalidFlowTransition(f"mission transition {state.phase} -> {target} is not allowed")
        state.phase = target
