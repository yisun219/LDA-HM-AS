"""Transparent deterministic mission ranking."""

from __future__ import annotations

from dataclasses import dataclass

from .models import Mission, PriorityWeights


@dataclass(frozen=True)
class RankedMission:
    mission: Mission
    score: float
    components: dict[str, float]


def score_mission(mission: Mission, weights: PriorityWeights) -> RankedMission:
    values = {
        name: getattr(mission.signals, name).score
        for name in PriorityWeights.model_fields
    }
    components = {name: values[name] * getattr(weights, name) for name in values}
    return RankedMission(mission, round(sum(components.values()), 6), components)


def rank_missions(missions: tuple[Mission, ...], weights: PriorityWeights) -> list[RankedMission]:
    return sorted(
        (score_mission(item, weights) for item in missions), key=lambda x: (-x.score, x.mission.id)
    )
