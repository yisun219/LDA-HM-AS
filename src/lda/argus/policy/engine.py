from __future__ import annotations

from lda.models import ALLOWED_ACTIONS, ManagerAction, WorldState


class PolicyViolation(ValueError):
    pass


class PolicyEngine:
    """Deterministic authorization boundary for all Manager actions."""

    def validate(self, action: ManagerAction, world: WorldState) -> None:
        try:
            action.validate_shape()
        except ValueError as exc:
            raise PolicyViolation(str(exc)) from exc
        if action.estimated_cost > world.budget.remaining_cost:
            raise PolicyViolation("requested cost exceeds remaining run budget")
        if len([m for m in world.missions if m.status == "ACTIVE"]) >= world.budget.max_active_missions \
                and action.action == "CREATE_MISSION":
            raise PolicyViolation("maximum active missions reached")
        if action.action in {"PAUSE_MISSION", "RESUME_MISSION", "STOP_MISSION", "CONTINUE_CANDIDATE",
                             "REPRIORITIZE_MISSION"} and not action.target_id:
            raise PolicyViolation("target_id is required for this action")
        if action.action == "CREATE_RESEARCH_SNAPSHOT" and not action.evidence_refs:
            raise PolicyViolation("research snapshots require evidence references")
        if action.action == "START_CAPABILITY_MISSION" and not action.target_id:
            raise PolicyViolation("capability mission requires a capability target")
        if action.action == "PROPOSE_STOP" and action.expected_value > 0:
            raise PolicyViolation("stop proposal cannot claim positive expected value")

    def apply(self, action: ManagerAction, world: WorldState) -> None:
        self.validate(action, world)
        if action.estimated_cost:
            world.budget.remaining_cost -= action.estimated_cost
            world.budget.spent_cost += action.estimated_cost
