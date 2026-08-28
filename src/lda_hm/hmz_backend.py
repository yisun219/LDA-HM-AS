"""Humanize 2 agent backend whose turns run inside the card's E2B sandbox.

The hmz runner drives sessions of this backend like any other backend: each
turn spawns one host-side relay process (`lda_hm.hmz_relay`) that pushes the
prompt into the card's live sandbox, executes the in-sandbox LDA agent
harness (claude/codex/pi with role-scoped tools and the Builder tool guard),
and prints the reply. Credentials stay E2B-resident; the relay carries none.

The role an agent plays is its hmz name (`agent.clone(name="builder")`), so
the six LDA roles are six named agents on the hmz trace, cloned from the two
the flow is handed. The in-sandbox conversation is keyed by a per-session
name, which is also the trace file the Builder-trace fence audits.
"""
from __future__ import annotations

import sys
import uuid
from typing import ClassVar

from hmz.agents import AgentBase, CommandSessionBase

_ROLES = ("drafter", "planner", "analyst", "builder", "reviewer", "supervisor")


class E2BHarnessSession(CommandSessionBase):
    """One in-sandbox conversation, resumed by name across its turns."""

    shapes: ClassVar[bool] = False

    def __init__(self, agent: "E2BHarnessAgent", cwd=None) -> None:
        super().__init__(agent, cwd)
        role = agent.role
        self.box_session = f"{role}-{uuid.uuid4().hex[:8]}"

    def _turn(self, prompt: str):
        agent = self._agent
        argv = [
            sys.executable,
            "-m",
            "lda_hm.hmz_relay",
            "--cwd",
            str(self.cwd or "."),
            "--role",
            agent.role,
            "--session",
            self.box_session,
            "--model",
            agent.config.model,
            "--effort",
            agent.config.effort,
        ]
        return argv, prompt

    def _read_session_id(self, transcript: str) -> str:
        for line in transcript.splitlines():
            if line.startswith("LDA-SESSION:"):
                return line.split(":", 1)[1].strip()
        return self.box_session


class E2BHarnessAgent(AgentBase):
    """An agent whose sessions are in-sandbox harness conversations."""

    moments: ClassVar[frozenset] = frozenset()
    pursues: ClassVar[bool] = False

    @property
    def role(self) -> str:
        name = (self.id or "builder").split("#", 1)[0]
        return name if name in _ROLES else "builder"

    def new(self, cwd=None) -> E2BHarnessSession:
        return E2BHarnessSession(self, cwd)
