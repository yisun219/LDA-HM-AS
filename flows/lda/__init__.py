"""LDA: agent-driven Ubuntu 26.04 package optimization under surgical-replacement fences.

The task is the absolute path of a card workspace prepared by `lda init-card`.
The flow clones its two agents into the six LDA roles (drafter, planner,
builder on the builder side; analyst, reviewer, supervisor on the reader
side), boots the card's pinned E2B sandbox, and runs the persistent-Builder /
fresh-Reviewer loop with every build, test, fence, and benchmark inside E2B.
Deterministic fences (upstream tests, ABI/FFI surgical-replacement checks,
Builder trace audit) gate every semantic review; certified speedups replay in
fresh sandboxes before finalize.
"""
from __future__ import annotations

from typing import NamedTuple

from hmz.flows import Agent, flow


class Places(NamedTuple):
    builder: Agent
    reviewer: Agent


@flow(resumable=True)
def run(agents: Places, task: str, state: dict) -> None:
    from pathlib import Path

    from lda_hm.hmz_glue import run_card

    run_card(agents.builder, agents.reviewer, Path(task), state)
