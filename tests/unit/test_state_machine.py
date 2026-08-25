import pytest

from lda.humanize import LDAMissionStateMachine, PureHumanizeStateMachine
from lda.humanize.state_machine import InvalidFlowTransition
from lda.models import MissionPhase, MissionState, RunPhase, RunState


def test_run_state_machine_blocks_skipping_fences() -> None:
    state = RunState(run_id="run", research_snapshot_id="research")
    with pytest.raises(InvalidFlowTransition):
        PureHumanizeStateMachine.transition(state, RunPhase.RELEASE_READY)
    PureHumanizeStateMachine.transition(state, RunPhase.E2B_PREFLIGHT)
    assert state.phase is RunPhase.E2B_PREFLIGHT


def test_mission_state_machine_blocks_direct_win() -> None:
    state = MissionState(mission_id="mission")
    with pytest.raises(InvalidFlowTransition):
        LDAMissionStateMachine.transition(state, MissionPhase.LOCAL_WIN)
