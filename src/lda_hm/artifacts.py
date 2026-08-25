from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import Any

from .types import FlowState


class ArtifactStore:
    def __init__(
        self,
        workspace: Path,
        run_id: str,
        *,
        results_root: Path | None = None,
    ) -> None:
        self.workspace = workspace.resolve()
        self.results_root = (
            results_root.resolve()
            if results_root is not None
            else self.workspace / ".lda-hm"
        )
        self.root = self.results_root / "runs" / run_id
        self.rounds = self.root / "rounds"
        self.root.mkdir(parents=True, exist_ok=True)
        self.rounds.mkdir(parents=True, exist_ok=True)

    @property
    def state_file(self) -> Path:
        return self.root / "state.json"

    def round_dir(self, number: int) -> Path:
        path = self.rounds / str(number)
        path.mkdir(parents=True, exist_ok=True)
        return path

    def write_text(self, relative: str | Path, content: str) -> Path:
        path = self.root / relative
        self._atomic_write(path, content.encode("utf-8"))
        return path

    def read_text(self, relative: str | Path) -> str:
        return (self.root / relative).read_text(encoding="utf-8")

    def write_json(self, relative: str | Path, value: Any) -> Path:
        content = json.dumps(value, indent=2, sort_keys=True) + "\n"
        return self.write_text(relative, content)

    def save_state(self, state: FlowState) -> None:
        self.write_json("state.json", state.to_dict())

    def load_state(self) -> FlowState:
        value = json.loads(self.state_file.read_text(encoding="utf-8"))
        if not isinstance(value, dict):
            raise ValueError("state must be a JSON object")
        return FlowState.from_dict(value)

    def seal_plan(self, plan: str) -> str:
        digest = hashlib.sha256(plan.encode("utf-8")).hexdigest()
        self.write_text("plan.md", plan)
        self.write_text("plan.sha256", digest + "\n")
        return digest

    def plan_is_intact(self, expected_hash: str = "") -> bool:
        plan = self.root / "plan.md"
        digest = self.root / "plan.sha256"
        if not plan.is_file() or not digest.is_file():
            return False
        actual = hashlib.sha256(plan.read_bytes()).hexdigest()
        stored = digest.read_text(encoding="utf-8").strip()
        return actual == stored and (not expected_hash or actual == expected_hash)

    @staticmethod
    def _atomic_write(path: Path, content: bytes) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
        try:
            temporary.write_bytes(content)
            os.replace(temporary, path)
        finally:
            temporary.unlink(missing_ok=True)
