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
                 builder: Agent, reviewer: Agent, cwd: Path,
                 supervisor: Agent | None = None) -> None:
        self.drafter = drafter.new_session(cwd)
        self.planner = planner.new_session(cwd)
        self.builder = builder.new_session(cwd)
        self._builder_agent = builder
        self._analyst = analyst
        self._reviewer = reviewer
        self._supervisor = supervisor
        self._cwd = cwd

    def fresh_analyst(self) -> Session:
        return self._analyst.new_session(self._cwd)

    def fresh_reviewer(self) -> Session:
        return self._reviewer.new_session(self._cwd)

    def fresh_supervisor(self) -> Session:
        if self._supervisor is None:
            raise ValueError("no supervisor agent is configured")
        return self._supervisor.new_session(self._cwd)

    @property
    def has_supervisor(self) -> bool:
        return self._supervisor is not None

    def builder_session_id(self) -> str:
        return str(getattr(self.builder, "session_id", "builder-1"))

    def restart_builder(self) -> str:
        """Open a fresh Builder session (poisoned/dead session recovery)."""
        self.builder = self._builder_agent.new_session(self._cwd)
        return self.builder_session_id()
