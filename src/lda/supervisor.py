from __future__ import annotations

import json
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
        # Recovery requeues a canary whose previous attempt produced invalid
        # evidence, rather than treating a transport/build failure as a
        # terminal success.  The attempt counter and event chain remain intact.
        for mission in self.world.missions:
            if mission.status == "SUCCEEDED" and mission.last_outcome == "BENCHMARK_INVALID" and mission.attempts < mission.max_attempts:
                mission.status = "QUEUED"
                self.store.append(self.world.run_id, str(self.world.life_cycle), "recovery", "MISSION_REQUEUED",
                                  payload={"mission_id": mission.mission_id, "reason": "invalid_benchmark_evidence"})

    @classmethod
    def bootstrap(cls, root: str | Path, run_id: str, *, client: E2BClient, packages: list[str],
                  campaign: dict[str, Any] | None = None, qualification: dict[str, Any] | None = None) -> "ArgusSupervisor":
        world = WorldState(run_id=run_id, campaign_input=campaign or {}, qualification=qualification or {})
        canary = list(dict.fromkeys((campaign or {}).get("canary", [])))
        canary_set = set(canary)
        for package in packages:
            priority = 0.95 if package in canary_set else 0.5
            world.missions.append(Mission(new_id("mission"), package, priority=priority, expected_value=priority))
        # ``packages`` is the initial canary authorization set.  The report's
        # Top 10 remain queued until both canaries pass the inner flow.
        qualified_top10 = []
        for row in (qualification or {}).get("results", []):
            checks = row.get("checks", {})
            if row.get("package") and all(isinstance(checks.get(name), dict) and checks[name].get("available") is True
                                           for name in ("binary_package", "source_mapping", "dependency_metadata", "build_tools")):
                qualified_top10.append(row["package"])
        world.convergence_signals["qualified_packages"] = qualified_top10 or list(packages)
        world.convergence_signals["canary_pending"] = list(canary)
        supervisor = cls(root, client=client, world=world)
        supervisor.store.save_world(world)
        supervisor.store.append(run_id, None, "controller", "BOOTSTRAP", payload={"packages": packages,
            "campaign_input_sha256": (campaign or {}).get("sha256"), "qualification": qualification or {}})
        return supervisor

    def _expand_after_canary(self) -> None:
        pending = self.world.convergence_signals.get("canary_pending", [])
        # A Judge-passing mission is not enough to release the portfolio: the
        # canary must have a recorded system-level outcome backed by valid
        # measured benchmark evidence for every package.
        canary_missions = [m for m in self.world.missions if m.package in pending]
        passed = all(self._canary_mission_passed(m) for m in canary_missions)
        if pending and len(canary_missions) == len(set(pending)) and passed:
            qualified = self.world.convergence_signals.get("qualified_packages", [])
            existing = {m.package for m in self.world.missions}
            for package in qualified:
                if package not in existing:
                    self.world.missions.append(Mission(new_id("mission"), package, priority=0.5, expected_value=0.5))
            self.world.convergence_signals["canary_pending"] = []
            self.store.append(self.world.run_id, str(self.world.life_cycle), "policy", "CANARY_RELEASE",
                              payload={"packages": qualified})

    def _canary_mission_passed(self, mission: Mission) -> bool:
        if mission.status != "SUCCEEDED":
            return False
        outcomes = [o for o in self.world.outcome_ledger if o.get("mission_id") == mission.mission_id]
        if not any(o.get("classification") == "SUCCESS_SYSTEM" for o in outcomes):
            return False
        benchmarks = [b for b in self.world.benchmark_ledger if b.get("mission_id") == mission.mission_id]
        if not benchmarks:
            return False
        benchmark = benchmarks[-1]
        if benchmark.get("invalid") or benchmark.get("accepted") is not True:
            return False
        portfolio = benchmark.get("portfolio", benchmark)
        return (
            portfolio.get("invalid") is not True
            and float(portfolio.get("geomean_speedup", 0.0)) >= 1.01
            and int(portfolio.get("improved_workloads", 0)) >= 2
        )

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
            benchmark = dict(result["benchmark"])
            benchmark["mission_id"] = mission.mission_id
            self.world.benchmark_ledger.append(benchmark)
            mission.last_outcome = classified.get("classification")
            return {"action": action.__dict__, "outcome": classified, "mission_id": mission.mission_id}
        if action.action == "RUN_PORTFOLIO_E2E":
            e2e = self.client.create({"project": "lda", "run_id": self.world.run_id,
                "life_cycle": str(self.world.life_cycle), "mission_id": "portfolio",
                "candidate_id": "none", "role": "e2e", "template": "lda-e2e", "lease_id": new_id("lease")})
            command_result = self.client.command(e2e, "./run-portfolio-e2e", background=False)
            portfolio = self._portfolio_from_result(command_result)
            self.client.kill(e2e)
            self.world.portfolio_e2e.append(portfolio)
            self.world.convergence_signals.update({"portfolio_geomean_speedup": portfolio["geomean_speedup"], "improved_workloads": portfolio["improved_workloads"]})
            return {"action": action.__dict__, "portfolio": portfolio}
        return {"action": action.__dict__, "status": "accepted"}

    @staticmethod
    def _portfolio_from_result(command_result: dict[str, Any]) -> dict[str, Any]:
        """Consume only JSON emitted by the E2E harness; never invent reward data."""
        if command_result.get("exit_code") != 0:
            return {"invalid": True, "geomean_speedup": 0.0, "improved_workloads": 0,
                    "reason": "portfolio_e2e_command_failed"}
        try:
            payload = json.loads(command_result.get("stdout", ""))
            workloads = payload["workloads"]
            return BenchmarkRunner().portfolio(workloads)
        except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
            return {"invalid": True, "geomean_speedup": 0.0, "improved_workloads": 0,
                    "reason": f"missing_or_invalid_portfolio_evidence: {exc}"}

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
        try:
            self.agents.run(manager, "Observe the world and emit one allowed ManagerAction as JSON.")
        except Exception as exc:
            # Manager output is advisory.  A provider/network stall must not
            # prevent the deterministic policy from making a bounded action.
            self.store.append(self.world.run_id, str(self.world.life_cycle), "argus-manager", "AGENT_FAILURE",
                              payload={"role": manager.role, "error": str(exc)})
        summary = self.agents.spec(run_id=self.world.run_id, life_cycle_id=str(self.world.life_cycle), role="World State Summarizer", independence_group="summarizer")
        self.agents.create(summary)
        try:
            self.agents.run(summary, "Summarize structured world facts without hidden reasoning.")
        except Exception as exc:
            self.store.append(self.world.run_id, str(self.world.life_cycle), "world-summarizer", "AGENT_FAILURE",
                              payload={"role": summary.role, "error": str(exc)})
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
