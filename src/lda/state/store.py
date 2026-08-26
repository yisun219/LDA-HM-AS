from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Any

from lda.models import Candidate, WorldState, new_id, stable_hash, utc_now
from lda.security.redaction import redact


class EventStore:
    """Append-only JSONL store with a hash chain and atomic world snapshots."""

    def __init__(self, root: str | Path):
        self.root = Path(root).resolve()
        self.meta = self.root / ".lda"
        self.events_path = self.meta / "events.jsonl"
        self.world_path = self.meta / "world.json"

    def ensure(self) -> None:
        self.meta.mkdir(parents=True, exist_ok=True)

    def append(self, run_id: str, cycle_id: str | None, actor: str, event_type: str,
               input_refs: list[str] | None = None, output_refs: list[str] | None = None,
               payload: dict[str, Any] | None = None) -> dict[str, Any]:
        self.ensure()
        previous = "GENESIS"
        if self.events_path.exists():
            with self.events_path.open(encoding="utf-8") as fh:
                for line in fh:
                    if line.strip():
                        previous = json.loads(line)["hash"]
        event = {
            "event_id": new_id("evt"), "run_id": run_id, "cycle_id": cycle_id,
            "actor": actor, "event_type": event_type, "input_refs": input_refs or [],
            "output_refs": output_refs or [], "timestamp": utc_now(), "previous_hash": previous,
            "payload": redact(payload or {}),
        }
        event["hash"] = stable_hash(event)
        with self.events_path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(event, sort_keys=True) + "\n")
            fh.flush()
            os.fsync(fh.fileno())
        return event

    def save_world(self, world: WorldState) -> None:
        self.ensure()
        fd, tmp = tempfile.mkstemp(prefix="world.", dir=self.meta)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                json.dump(world.dump(), fh, indent=2, sort_keys=True)
                fh.write("\n")
                fh.flush()
                os.fsync(fh.fileno())
            os.replace(tmp, self.world_path)
        finally:
            if os.path.exists(tmp):
                os.unlink(tmp)

    def load_world(self) -> WorldState:
        with self.world_path.open(encoding="utf-8") as fh:
            return WorldState.load(json.load(fh))

    def recover(self) -> WorldState:
        world = self.load_world()
        # Candidate artifacts are persisted before a mission sandbox is
        # destroyed. Replaying these events closes the crash window between
        # the append-only record and the next atomic world snapshot.
        for event in self.events():
            if event.get("event_type") != "CANDIDATE_ARTIFACTS":
                continue
            payload = event.get("payload", {})
            raw = payload.get("candidate")
            if not isinstance(raw, dict) or not raw.get("candidate_id") or not raw.get("mission_id"):
                continue
            replayed = Candidate(**raw)
            candidate = next((item for item in world.candidates
                              if item.candidate_id == raw["candidate_id"]), None)
            if candidate is None:
                world.candidates.append(replayed)
            else:
                for name in candidate.__dataclass_fields__:
                    if name not in {"candidate_id", "mission_id"}:
                        setattr(candidate, name, getattr(replayed, name))
        return world

    def events(self) -> list[dict[str, Any]]:
        if not self.events_path.exists():
            return []
        with self.events_path.open(encoding="utf-8") as fh:
            return [json.loads(line) for line in fh if line.strip()]
