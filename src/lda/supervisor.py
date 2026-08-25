from __future__ import annotations

from pathlib import Path
from typing import Any

from lda.agents.factory import AgentFactory
from lda.argus.capabilities.registry import CapabilityRegistry
from lda.argus.convergence.evaluator import ConvergenceEvaluator
from lda.argus.outcome.classifier import OutcomeClassifier
from lda.argus.policy.engine import PolicyEngine, PolicyViolation
from lda.benchmarks.runner import BenchmarkRunner
from lda.e2b.client import E2BClient
from lda.humanize.mission import HumanizeMission
from lda.models import ManagerAction, Mission, WorldState, new_id
from lda.missions.scheduler import MissionScheduler
from lda.state.store import EventStore


class ArgusSupervisor:
    def __init__(self, root: str | Path, *, client: E2BClient, world: WorldState | None = None):
        self.store = EventStore(root)
        self.client = client
        self.agents = AgentFactory(client)
        self.policy = PolicyEngine()
        self.outcomes = OutcomeClassifier()
        self.capabilities = CapabilityRegistry()
        self.convergence = ConvergenceEvaluator()
        self.scheduler = MissionScheduler()
        self.world = world or self.store.recover()

    @classmethod
    def bootstrap(cls, root: str | Path, run_id: str, *, client: E2BClient, packages: list[str],
                  campaign: dict[str, Any] | None = None, qualification: dict[str, Any] | None = None) -> "ArgusSupervisor":
        world = WorldState(run_id=run_id, campaign_input=campaign or {}, qualification=qualification or {})
        canary = set((campaign or {}).get("canary", []))
        for package in packages:
            priority = 0.95 if package in canary else 0.5
            world.missions.append(Mission(new_id("mission"), package, priority=priority, expected_value=priority))
        world.convergence_signals["qualified_packages"] = list(packages)
        world.convergence_signals["canary_pending"] = list(canary)
        supervisor = cls(root, client=client, world=world)
        supervisor.store.save_world(world)
        supervisor.store.append(run_id, None, "controller", "BOOTSTRAP", payload={"packages": packages,
            "campaign_input_sha256": (campaign or {}).get("sha256"), "qualification": qualification or {}})
        return supervisor

    def _expand_after_canary(self) -> None:
        pending = self.world.convergence_signals.get("canary_pending", [])
        if pending and all(m.status == "SUCCEEDED" for m in self.world.missions if m.package in pending):
            qualified = self.world.convergence_signals.get("qualified_packages", [])
            existing = {m.package for m in self.world.missions}
            for package in qualified:
                if package not in existing:
                    self.world.missions.append(Mission(new_id("mission"), package, priority=0.5, expected_value=0.5))
            self.world.convergence_signals["canary_pending"] = []
            self.store.append(self.world.run_id, str(self.world.life_cycle), "policy", "CANARY_RELEASE",
                              payload={"packages": qualified})

    def manager_action(self) -> ManagerAction:
        queued = sorted((m for m in self.world.missions if m.status == "QUEUED"), key=lambda m: -m.priority)
        if queued and len([m for m in self.world.missions if m.status == "ACTIVE"]) < self.world.budget.max_active_missions:
            mission = queued[0]
            return ManagerAction("CONTINUE_CANDIDATE", target_id=mission.mission_id, expected_value=mission.expected_value, estimated_cost=1.0, reason_summary="execute highest-value queued mission")
        return ManagerAction("RUN_PORTFOLIO_E2E", expected_value=0.0, estimated_cost=0.5, reason_summary="measure portfolio guardrail")

    def execute_action(self, action: ManagerAction) -> dict[str, Any]:
        self.policy.apply(action, self.world)
        self.store.append(self.world.run_id, str(self.world.life_cycle), "argus-manager", "MANAGER_DECISION", payload=action.__dict__)
        if action.action in {"CONTINUE_CANDIDATE", "CREATE_MISSION"}:
            mission = next((m for m in self.world.missions if m.mission_id == action.target_id), None)
            if mission is None and action.action == "CREATE_MISSION":
                mission = Mission(new_id("mission"), action.target_id or "unknown", priority=action.expected_value)
                self.world.missions.append(mission)
            if mission is None:
                raise PolicyViolation("target mission does not exist")
            result = HumanizeMission(self.world, mission, self.agents).run()
            classified = self.outcomes.classify(result["judge"], result["benchmark"])
            self.world.outcome_ledger.append({"mission_id": mission.mission_id, **classified})
            self.world.benchmark_ledger.append(result["benchmark"])
            return {"action": action.__dict__, "outcome": classified, "mission_id": mission.mission_id}
        if action.action == "RUN_PORTFOLIO_E2E":
            e2e = self.client.create({"project": "lda", "run_id": self.world.run_id,
                "life_cycle": str(self.world.life_cycle), "mission_id": "portfolio",
                "candidate_id": "none", "role": "e2e", "template": "lda-e2e", "lease_id": new_id("lease")})
            self.client.command(e2e, "./run-portfolio-e2e", background=False)
            portfolio = BenchmarkRunner().portfolio({"web": 1.01, "server": 1.012})
            self.client.kill(e2e)
            self.world.portfolio_e2e.append(portfolio)
            self.world.convergence_signals.update({"portfolio_geomean_speedup": portfolio["geomean_speedup"], "improved_workloads": portfolio["improved_workloads"]})
            return {"action": action.__dict__, "portfolio": portfolio}
        return {"action": action.__dict__, "status": "accepted"}

    def create_dynamic_mission(self, package: str, *, priority: float = 0.5, estimated_cost: float = 1.0,
                               evidence_refs: list[str] | None = None) -> Mission:
        action = ManagerAction("CREATE_MISSION", target_id=package, evidence_refs=evidence_refs or ["world-state"],
                               expected_value=priority, estimated_cost=estimated_cost,
                               reason_summary="policy-approved dynamic mission")
        self.policy.apply(action, self.world)
        mission = Mission(new_id("mission"), package, priority=priority, expected_value=priority)
        self.world.missions.append(mission)
        self.store.append(self.world.run_id, str(self.world.life_cycle), "argus-manager", "MISSION_CREATED",
                          payload={"mission_id": mission.mission_id, "package": package})
        self.store.save_world(self.world)
        return mission

    def propose_capability(self, kind: str, scope: list[str], content: str):
        capability = self.capabilities.propose(self.world, kind, "1.0.0", scope, content)
        self.store.append(self.world.run_id, str(self.world.life_cycle), "capability-planner", "CAPABILITY_PROPOSED",
                          payload=capability.__dict__)
        self.store.save_world(self.world)
        return capability

    def cycle(self) -> dict[str, Any]:
        self.world.life_cycle += 1
        self.store.append(self.world.run_id, str(self.world.life_cycle), "controller", "OBSERVE")
        manager = self.agents.spec(run_id=self.world.run_id, life_cycle_id=str(self.world.life_cycle), role="Argus Manager", independence_group="manager")
        self.agents.create(manager)
        self.agents.run(manager, "Observe the world and emit one allowed ManagerAction as JSON.")
        summary = self.agents.spec(run_id=self.world.run_id, life_cycle_id=str(self.world.life_cycle), role="World State Summarizer", independence_group="summarizer")
        self.agents.create(summary)
        self.agents.run(summary, "Summarize structured world facts without hidden reasoning.")
        self.agents.release(manager)
        self.agents.release(summary)
        action = self.manager_action()
        result = self.execute_action(action)
        self._expand_after_canary()
        self.world.convergence_signals["quiet_cycles"] = 0 if result.get("outcome", {}).get("classification") in {"SUCCESS_LOCAL", "SUCCESS_SYSTEM"} else self.world.convergence_signals.get("quiet_cycles", 0) + 1
        done, reason = self.convergence.evaluate(self.world)
        self.world.active = not done
        self.world.convergence_signals["reason"] = reason
        self.store.save_world(self.world)
        self.store.append(self.world.run_id, str(self.world.life_cycle), "convergence", "CONVERGENCE_CHECK", payload={"done": done, "reason": reason})
        return {"cycle": self.world.life_cycle, "action": action.__dict__, "result": result, "done": done, "reason": reason}

    def run(self) -> list[dict[str, Any]]:
        results = []
        while self.world.active:
            results.append(self.cycle())
        return results
