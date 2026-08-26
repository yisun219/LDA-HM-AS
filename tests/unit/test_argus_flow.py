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

    def test_dynamic_mission_requires_qualification_evidence_and_budget(self):
        world = WorldState("r")
        world.convergence_signals["qualified_packages"] = ["libcairo2"]
        policy = PolicyEngine()
        with self.assertRaises(PolicyViolation):
            policy.validate(ManagerAction("CREATE_MISSION", target_id="unknown",
                                          evidence_refs=["research"], estimated_cost=1), world)
        with self.assertRaises(PolicyViolation):
            policy.validate(ManagerAction("CREATE_MISSION", target_id="libcairo2",
                                          evidence_refs=["research"], estimated_cost=101), world)
        policy.validate(ManagerAction("CREATE_MISSION", target_id="libcairo2",
                                      evidence_refs=["research"], estimated_cost=1), world)

    def test_manager_stop_proposal_cannot_override_convergence(self):
        world = WorldState("r")
        world.missions.append(Mission("m", "libcairo2", priority=0.9))
        world.convergence_signals["manager_stop_proposed"] = True
        self.assertEqual(ConvergenceEvaluator().evaluate(world), (False, "continue"))

    def test_manager_action_parser_and_mission_controls(self):
        raw = {"action": "REPRIORITIZE_MISSION", "target_id": "m", "evidence_refs": [],
               "expected_value": 0.8, "estimated_cost": 0.0, "risk": 0.1,
               "reason_summary": "measured criticality", "requested_budget": {}, "preconditions": []}
        action = ArgusSupervisor._action_from_output(raw)
        self.assertIsNotNone(action)
        with tempfile.TemporaryDirectory() as tmp:
            world = WorldState("r", missions=[Mission("m", "libcairo2", priority=0.5)])
            supervisor = ArgusSupervisor(tmp, client=E2BClient(fake=True), world=world)
            supervisor.execute_action(action)
            self.assertEqual(world.missions[0].priority, 0.8)
            supervisor.execute_action(ManagerAction("PAUSE_MISSION", target_id="m"))
            self.assertEqual(world.missions[0].status, "PAUSED")
            supervisor.execute_action(ManagerAction("RESUME_MISSION", target_id="m"))
            self.assertEqual(world.missions[0].status, "QUEUED")

    def test_capability_activation_requires_judge(self):
        world = WorldState("r")
        registry = CapabilityRegistry()
        cap = registry.propose(world, "profiler", "1", ["zlib"], "adapter")
        with self.assertRaises(ValueError):
            registry.transition(cap, "CAPABILITY_JUDGE")
        registry.transition(cap, "POLICY_APPROVED")
        registry.transition(cap, "BUILDING")
        registry.transition(cap, "ISOLATED_TEST", tests_passed=True)
        registry.transition(cap, "ADVERSARIAL_REVIEW")
        registry.transition(cap, "CAPABILITY_JUDGE")
        with self.assertRaises(ValueError):
            registry.transition(cap, "ACTIVE")
        registry.transition(cap, "ACTIVE", judge_passed=True)
        self.assertEqual(cap.status, "ACTIVE")
        self.assertTrue(cap.tests_passed)
        self.assertTrue(cap.judge_passed)

    def test_capability_cannot_skip_or_leave_terminal_state(self):
        world = WorldState("r")
        registry = CapabilityRegistry()
        cap = registry.propose(world, "build-adapter", "1", ["cairo"], "adapter")
        with self.assertRaisesRegex(ValueError, "POLICY_APPROVED"):
            registry.transition(cap, "BUILDING")
        registry.transition(cap, "POLICY_APPROVED")
        registry.transition(cap, "BUILDING")
        with self.assertRaisesRegex(ValueError, "isolated tests must pass"):
            registry.transition(cap, "ISOLATED_TEST")
        registry.transition(cap, "REJECTED")
        with self.assertRaisesRegex(ValueError, "terminal"):
            registry.transition(cap, "ACTIVE", judge_passed=True)

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
        class CodexClient(E2BClient):
            def command(self, sandbox, command, **kwargs):
                thread = "builder-real-thread" if sandbox.metadata.get("role") == "Builder" else "reviewer-real-thread"
                payload = '{"hypothesis":"h","cflags":[],"cxxflags":[],"expected_effect":"e","evidence_refs":[]}'
                stdout = ('{"type":"thread.started","thread_id":"' + thread + '"}\n'
                          + '{"type":"item.completed","item":{"type":"agent_message","text":'
                          + __import__("json").dumps(payload) + '}}\n')
                return {"exit_code": 0, "stdout": stdout, "stderr": ""}

        factory = AgentFactory(CodexClient(fake=True))
        builder = factory.spec(run_id="r", life_cycle_id="1", mission_id="m", candidate_id="c", role="Builder", independence_group="builder")
        factory.create(builder)
        first = factory.run(builder, "first")
        second = factory.run(builder, "second")
        self.assertEqual(first["session_id"], "builder-real-thread")
        self.assertEqual(first["output"]["hypothesis"], "h")
        self.assertTrue(second["resumed"])
        reviewer = factory.spec(run_id="r", life_cycle_id="1", mission_id="m", candidate_id="c", role="Reviewer", independence_group="reviewer")
        factory.create(reviewer)
        review = factory.run(reviewer, "review")
        self.assertFalse(review["resumed"])
        self.assertNotEqual(factory.sessions["Builder:builder:c"], factory.sessions["Reviewer:reviewer:c"])

    def test_codex_resume_command_never_uses_yolo(self):
        command = E2BClient(fake=True).codex_command("continue", session_id="session-123")
        self.assertIn("exec resume", command)
        self.assertIn("session-123", command)
        self.assertNotIn("yolo", command)
        self.assertNotIn("dangerously-bypass", command)

    def test_persistent_agent_runtime_recovers_from_world_state(self):
        class CodexClient(E2BClient):
            def command(self, sandbox, command, **kwargs):
                return {"exit_code": 0,
                        "stdout": '{"type":"thread.started","thread_id":"real-session"}\n',
                        "stderr": ""}

        client = CodexClient(fake=True)
        state = {}
        first = AgentFactory(client, state)
        builder = first.spec(run_id="r", life_cycle_id="1", mission_id="m", candidate_id="c",
                             role="Builder", independence_group="builder")
        _, original_box = first.create(builder)
        first.run(builder, "first")
        self.assertEqual(state["Builder:builder:c"]["session_id"], "real-session")

        recovered = AgentFactory(client, state)
        _, recovered_box = recovered.create(builder)
        self.assertEqual(recovered_box.sandbox_id, original_box.sandbox_id)
        self.assertTrue(recovered.run(builder, "continue")["resumed"])

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
