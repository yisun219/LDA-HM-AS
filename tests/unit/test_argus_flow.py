import tempfile
import unittest
from pathlib import Path

from lda.agents.factory import AgentFactory
from lda.argus.capabilities.registry import CapabilityRegistry
from lda.argus.convergence.evaluator import ConvergenceEvaluator
from lda.controller.supervisor import ArgusSupervisor
from lda.argus.policy.engine import PolicyEngine, PolicyViolation
from lda.e2b.client import E2BClient
from lda.e2b.gateway import GatewayConfig, SharedGateway
from lda.models import ManagerAction, WorldState
from lda.models import Mission
from lda.research.campaign import CANARY, TOP10
from lda.state.store import EventStore


class ArgusFlowTest(unittest.TestCase):
    def test_gateway_preserves_sdk_headers_and_adds_key(self):
        gateway = SharedGateway(GatewayConfig(api_url="x", sandbox_url="x", validate_api_key=False))
        headers = gateway.headers({"E2b-Sandbox-Id": "s", "E2b-Sandbox-Port": "80", "User-Agent": "sdk"})
        self.assertEqual(headers["E2b-Sandbox-Id"], "s")
        self.assertEqual(headers["User-Agent"], "sdk")
        self.assertIn("X-API-KEY", headers)

    def test_policy_rejects_fence_like_unsupported_action(self):
        with self.assertRaises(PolicyViolation):
            PolicyEngine().validate(ManagerAction("MODIFY_FENCE"), WorldState("r"))

    def test_capability_activation_requires_judge(self):
        world = WorldState("r")
        registry = CapabilityRegistry()
        cap = registry.propose(world, "profiler", "1", ["zlib"], "adapter")
        with self.assertRaises(ValueError):
            registry.transition(cap, "ACTIVE")
        registry.transition(cap, "CAPABILITY_JUDGE", judge_passed=True)
        registry.transition(cap, "ACTIVE", judge_passed=True)
        self.assertEqual(cap.status, "ACTIVE")

    def test_event_store_recovers_after_controller_restart(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = EventStore(tmp)
            world = WorldState("r")
            store.save_world(world)
            store.append("r", "1", "controller", "BOOTSTRAP")
            recovered = store.recover()
            self.assertEqual(recovered.run_id, "r")
            self.assertEqual(len(store.events()), 1)

    def test_agent_sessions_follow_independence_policy(self):
        factory = AgentFactory(E2BClient(fake=True))
        builder = factory.spec(run_id="r", life_cycle_id="1", mission_id="m", candidate_id="c", role="Builder", independence_group="builder")
        first = factory.create(builder)
        second = factory.create(builder)
        self.assertEqual(factory.sessions["Builder:builder:c"], factory.sessions["Builder:builder:c"])
        reviewer = factory.spec(run_id="r", life_cycle_id="1", mission_id="m", candidate_id="c", role="Reviewer", independence_group="reviewer")
        factory.create(reviewer)
        self.assertNotEqual(factory.sessions["Builder:builder:c"], factory.sessions["Reviewer:reviewer:c"])

    def test_convergence_is_deterministic(self):
        world = WorldState("r", life_cycle=20)
        self.assertEqual(ConvergenceEvaluator().evaluate(world), (True, "max_life_cycles"))

    def test_portfolio_reward_requires_harness_evidence(self):
        result = ArgusSupervisor._portfolio_from_result({"exit_code": 0, "stdout": ""})
        self.assertTrue(result["invalid"])
        self.assertEqual(result["geomean_speedup"], 0.0)

    def test_top10_expansion_requires_system_outcome_and_measured_e2e(self):
        with tempfile.TemporaryDirectory() as tmp:
            qualification = {"results": [{"package": package, "checks": {
                name: {"available": True} for name in
                ("binary_package", "source_mapping", "dependency_metadata", "build_tools")
            }} for package in TOP10]}
            supervisor = ArgusSupervisor.bootstrap(
                tmp, "r", client=E2BClient(fake=True), packages=CANARY,
                campaign={"canary": CANARY, "top10": TOP10}, qualification=qualification)
            canary_missions = [m for m in supervisor.world.missions if m.package in CANARY]
            for mission in canary_missions:
                mission.status = "SUCCEEDED"
                supervisor.world.outcome_ledger.append({"mission_id": mission.mission_id,
                                                        "classification": "SUCCESS_LOCAL"})
                supervisor.world.benchmark_ledger.append({"mission_id": mission.mission_id,
                                                          "accepted": True, "invalid": False,
                                                          "portfolio": {"invalid": False,
                                                                        "geomean_speedup": 1.03,
                                                                        "improved_workloads": 2}})
            supervisor._expand_after_canary()
            self.assertEqual(set(supervisor.world.convergence_signals["canary_pending"]), set(CANARY))
            self.assertEqual({m.package for m in supervisor.world.missions}, set(CANARY))

            for mission in canary_missions:
                supervisor.world.outcome_ledger.append({"mission_id": mission.mission_id,
                                                        "classification": "SUCCESS_SYSTEM"})
            supervisor._expand_after_canary()
            self.assertEqual(supervisor.world.convergence_signals["canary_pending"], [])
            self.assertEqual({m.package for m in supervisor.world.missions}, set(TOP10))
