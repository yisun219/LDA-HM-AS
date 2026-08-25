from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from lda.models import MissionQueue, PackageScore, ResearchSnapshot, stable_digest


class InventoryMetrics(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    package: str
    usage_frequency: float = Field(ge=0, le=1)
    measured_cpu_share: float = Field(ge=0, le=1)
    dependency_centrality: float = Field(ge=0, le=1)
    workload_generality: float = Field(ge=0, le=1)
    expected_effort_efficiency: float = Field(ge=0, le=1)
    compatibility_risk: float = Field(ge=0, le=1)


def score_package(metrics: InventoryMetrics) -> PackageScore:
    priority = (
        0.25 * metrics.usage_frequency
        + 0.25 * metrics.measured_cpu_share
        + 0.20 * metrics.dependency_centrality
        + 0.15 * metrics.workload_generality
        + 0.15 * metrics.expected_effort_efficiency
        - metrics.compatibility_risk
    )
    return PackageScore(**metrics.model_dump(), priority=priority)


def freeze_mission_queue(
    run_id: str,
    snapshot: ResearchSnapshot,
    inventory: list[InventoryMetrics],
    *,
    limit: int = 10,
) -> MissionQueue:
    if not 1 <= limit <= 10:
        raise ValueError("mission queue limit must be between 1 and 10")
    hinted = {hint.package for hint in snapshot.hints}
    scores = sorted(
        (score_package(item) for item in inventory if item.package in hinted),
        key=lambda item: (-item.priority, item.package),
    )[:limit]
    if not scores:
        raise ValueError("no research package has inventory evidence")
    missions = [score.package for score in scores]
    payload = {
        "run_id": run_id,
        "research_snapshot_id": snapshot.snapshot_id,
        "missions": missions,
        "scores": [score.model_dump(mode="json") for score in scores],
    }
    return MissionQueue(
        **payload,
        queue_hash=stable_digest(payload),
    )
