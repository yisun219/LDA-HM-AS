from __future__ import annotations

from lda.models import Mission, WorldState, new_id


class MissionScheduler:
    """Separates Pure Humanize's fixed queue from Argus's policy-controlled graph."""

    def fixed_queue(self, packages: list[str]) -> list[Mission]:
        return [Mission(new_id("mission"), package, priority=0.5) for package in packages]

    def dynamic_add(self, world: WorldState, package: str, priority: float, estimated_cost: float) -> Mission:
        if estimated_cost > world.budget.remaining_cost:
            raise ValueError("dynamic mission exceeds global budget")
        mission = Mission(new_id("mission"), package, priority=priority)
        world.missions.append(mission)
        world.budget.remaining_cost -= estimated_cost
        world.budget.spent_cost += estimated_cost
        return mission

    def reprioritize(self, world: WorldState, mission_id: str, priority: float) -> None:
        mission = next((m for m in world.missions if m.mission_id == mission_id), None)
        if mission is None:
            raise ValueError("unknown mission")
        mission.priority = max(0.0, min(1.0, priority))

    def pause(self, world: WorldState, mission_id: str) -> None:
        mission = next((m for m in world.missions if m.mission_id == mission_id), None)
        if mission is None:
            raise ValueError("unknown mission")
        mission.status = "PAUSED"

    def resume(self, world: WorldState, mission_id: str) -> None:
        mission = next((m for m in world.missions if m.mission_id == mission_id), None)
        if mission is None:
            raise ValueError("unknown mission")
        if mission.status == "PAUSED":
            mission.status = "QUEUED"

