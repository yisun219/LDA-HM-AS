"""LDA package mission Flow, driven by pinned Humanize2."""

from __future__ import annotations

from pathlib import Path
from typing import Any, NamedTuple

from hmz.flows import Agent, flow
from pydantic import BaseModel, Field


class Agents(NamedTuple):
    builder: Agent
    reviewer: Agent


class Review(BaseModel):
    model_config = {"extra": "forbid"}
    approved: bool = Field(
        description="True only when all hard fences and benchmarks pass and no work remains."
    )
    blockers: list[str] = Field(
        default_factory=list, description="Concrete blockers with files and commands."
    )
    notes_for_builder: str = Field(
        description="The complete next prompt for the persistent Builder."
    )


class FlowConfig(BaseModel):
    model_config = {"extra": "forbid"}
    max_rounds: int = Field(default=12, ge=1, le=100)
    max_stalled_rounds: int = Field(default=3, ge=1, le=10)


@flow(resumable=True)
def run(
    agents: Agents,
    task: str,
    config: FlowConfig | None = None,
    state: dict[str, Any] | None = None,
) -> None:
    """Ralph-style Builder loop with a fresh structured Reviewer each round.

    Programmatic fences are executed by the Controller between turns. The task prompt
    contains the latest immutable fence report and never grants the Builder permission to
    alter tests, benchmarks, policy, or evidence.
    """
    settings = config or FlowConfig()
    kept = state if state is not None else {}
    builder = agents.builder.new()
    prompt = kept.get("next_prompt") or task
    stalled = int(kept.get("stalled_rounds", 0))
    round_number = int(kept.get("round", 0))
    while round_number < settings.max_rounds and stalled < settings.max_stalled_rounds:
        round_number += 1
        kept.update(round=round_number, phase="builder", next_prompt=prompt)
        worked = builder(prompt, suppress=True)
        if not worked:
            stalled += 1
            prompt = (
                "The Builder turn did not land. Re-read the repository and make one bounded change."
            )
            kept["stalled_rounds"] = stalled
            continue
        review = agents.reviewer(
            task
            + "\n\nRead the current Fence Report and raw benchmark evidence. Do not modify files.",
            suppress=True,
            schema=Review,
        )
        if review is None:
            stalled += 1
            prompt = (
                "Reviewer returned no valid structured result. Re-read the latest fence "
                "evidence and make one bounded improvement."
            )
        elif review.approved:
            Path("/workspace/mission/.lda/review-approved.json").parent.mkdir(
                parents=True, exist_ok=True
            )
            Path("/workspace/mission/.lda/review-approved.json").write_text(
                review.model_dump_json() + "\n", encoding="utf-8"
            )
            kept.clear()
            return
        else:
            stalled = 0
            prompt = (
                review.notes_for_builder
                or "Fix every reviewer blocker and rerun the programmatic fences."
            )
        kept.update(round=round_number, phase="review", next_prompt=prompt, stalled_rounds=stalled)
