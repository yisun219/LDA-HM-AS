from __future__ import annotations

from lda.models import WorldState


class ConvergenceEvaluator:
    def __init__(self, max_cycles: int = 20, min_geomean: float = 1.01, quiet_cycles: int = 3):
        self.max_cycles = max_cycles
        self.min_geomean = min_geomean
        self.quiet_cycles = quiet_cycles

    def evaluate(self, world: WorldState) -> tuple[bool, str]:
        signals = world.convergence_signals
        if world.life_cycle >= self.max_cycles:
            return True, "max_life_cycles"
        if world.budget.remaining_cost <= 0:
            return True, "budget_exhausted"
        if signals.get("quiet_cycles", 0) >= self.quiet_cycles:
            return True, "no_progress_for_three_cycles"
        active_high = [m for m in world.missions if m.status in {"QUEUED", "ACTIVE"} and m.priority >= 0.5]
        if not active_high and world.missions:
            return True, "all_high_priority_missions_terminated"
        geomean = signals.get("portfolio_geomean_speedup")
        if geomean is not None and geomean >= self.min_geomean and signals.get("improved_workloads", 0) >= 2:
            return True, "portfolio_target_reached"
        return False, "continue"

