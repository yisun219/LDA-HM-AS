from pathlib import Path

from lda.models import RunState
from lda.state import EventStore


def test_controller_crash_recovery(tmp_path: Path) -> None:
    store = EventStore(tmp_path)
    state = RunState(run_id="run-1", research_snapshot_id="research-1")
    store.save_run(state, "created")
    recovered = EventStore(tmp_path).load_run("run-1")
    assert recovered == state
    assert [event.kind for event in store.list_events("run-1")] == ["created"]
    assert (tmp_path / "runs" / "run-1.json").exists()
