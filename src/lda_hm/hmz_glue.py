"""Adapters that let the Humanize 2 harness drive the LDA engine.

The flow (`flows/lda`) hands this module two hmz agents (a builder side and
a reviewer side). They are cloned into the six LDA roles, wrapped in the
engine's Agent/Session protocol, and handed to the shared driver - so the
loop, sessions, retries, traces and resume belong to hmz, while fences,
benchmarks, cards and supervision stay the flow content they are.

This module deliberately never imports hmz: it talks to the agents through
their public surface (clone / new / call), so the engine tests can drive it
with stubs on any Python.
"""
from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any, Optional

from .driver import drive
from .runtime import SessionTopology

WRITER_ROLES = ("drafter", "planner", "builder")
READER_ROLES = ("analyst", "reviewer", "supervisor")


class RoleSession:
    """lda_hm Session protocol over one hmz session."""

    def __init__(self, session: Any) -> None:
        self._session = session
        self.session_id = str(
            getattr(session, "box_session", "") or getattr(session, "id", "") or "session"
        )

    def ask(self, prompt: str, *, schema=None):
        try:
            answer = self._session(prompt)
        except Exception as error:
            # hmz raises subprocess.CalledProcessError subclasses; the engine's
            # sentry logic keys off RuntimeError, so translate without losing
            # the failure sentence.
            raise RuntimeError(f"agent turn failed: {str(error)[-1500:]}") from error
        text = "" if answer is None else str(answer)
        if not text.strip():
            raise RuntimeError("agent returned an empty answer")
        return text


class RoleAgent:
    """lda_hm Agent protocol over one hmz agent clone."""

    def __init__(self, hmz_agent: Any) -> None:
        self._agent = hmz_agent

    def new_session(self, cwd: Path) -> RoleSession:
        return RoleSession(self._agent.new(cwd))


def role_agents(builder_side: Any, reviewer_side: Any) -> dict:
    """Clone the two handed agents into the six named LDA roles."""
    agents: dict[str, RoleAgent] = {}
    for role in WRITER_ROLES:
        agents[role] = RoleAgent(builder_side.clone(name=role))
    for role in READER_ROLES:
        agents[role] = RoleAgent(reviewer_side.clone(name=role))
    return agents


def run_card(builder_side: Any, reviewer_side: Any, workspace: Path, state: dict) -> None:
    """Drive one card workspace to a terminal phase under the hmz harness."""
    workspace = Path(workspace).resolve()
    run_id = (
        str(state.get("run_id") or "")
        or os.getenv("LDA_RUN_ID", "")
        or time.strftime("hmz-%Y%m%dT%H%M%S")
    )
    state["run_id"] = run_id
    state["workspace"] = str(workspace)
    results_root: Optional[Path] = (
        Path(os.environ["LDA_RESULTS_ROOT"]) if os.getenv("LDA_RESULTS_ROOT") else None
    )

    brokers = []

    def on_sandbox(sandbox) -> None:
        from .broker import SandboxBroker

        live = workspace / ".lda-hm" / "live-sandbox.json"
        live.parent.mkdir(parents=True, exist_ok=True)
        socket_path = workspace / ".lda-hm" / "broker.sock"
        for stale in brokers:
            stale.close()
        brokers.clear()
        broker = SandboxBroker(sandbox, socket_path)
        broker.start()
        brokers.append(broker)
        live.write_text(
            json.dumps(
                {
                    "sandbox_id": sandbox.sandbox_id,
                    "broker": str(socket_path),
                    "epoch": time.time(),
                }
            )
            + "\n",
            encoding="utf-8",
        )

    def topology_factory(sandbox, workspace_path: Path) -> SessionTopology:
        return SessionTopology(cwd=workspace_path, **role_agents(builder_side, reviewer_side))

    flow = drive(
        workspace,
        run_id=run_id,
        results_root=results_root,
        topology_factory=topology_factory,
        task=os.getenv("LDA_TASK", ""),
        contract=os.getenv(
            "LDA_CONTRACT", "Advance the highest-priority unmet acceptance criterion"
        ),
        on_sandbox=on_sandbox,
    )
    state["phase"] = flow.state.phase.value
    state["round"] = flow.state.current_round
    if flow.state.terminal_reason is not None:
        state["terminal_reason"] = flow.state.terminal_reason.value
