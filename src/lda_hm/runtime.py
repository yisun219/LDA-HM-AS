from __future__ import annotations

from pathlib import Path
from typing import Any, Protocol, TypeVar


Structured = TypeVar("Structured")


class Session(Protocol):
    """A conversation held by a backend."""

    def ask(
        self,
        prompt: str,
        *,
        schema: type[Structured] | None = None,
    ) -> str | Structured: ...


class Agent(Protocol):
    """A runtime-neutral agent that can open independent sessions."""

    def new_session(self, cwd: Path) -> Session: ...


class Human(Protocol):
    """The explicit escalation point for unresolved decisions."""

    def decide(self, question: str, context: dict[str, Any]) -> str: ...


class SessionTopology:
    """Documents and enforces writer/reader session ownership."""

    def __init__(self, *, drafter: Agent, planner: Agent, analyst: Agent,
                 builder: Agent, reviewer: Agent, cwd: Path) -> None:
        self.drafter = drafter.new_session(cwd)
        self.planner = planner.new_session(cwd)
        self.builder = builder.new_session(cwd)
        self._analyst = analyst
        self._reviewer = reviewer
        self._cwd = cwd

    def fresh_analyst(self) -> Session:
        return self._analyst.new_session(self._cwd)

    def fresh_reviewer(self) -> Session:
        return self._reviewer.new_session(self._cwd)
