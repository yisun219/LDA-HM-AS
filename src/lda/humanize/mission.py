from __future__ import annotations

import json
from typing import Any

from lda.agents.factory import AgentFactory
from lda.benchmarks.runner import BenchmarkRunner
from lda.fences.abi import CompatibilityFence, FenceManifest
from lda.judge.anti_cheat import AntiCheat
from lda.judge.clean import CleanJudge
from lda.missions.contract import MissionContract
from lda.models import Candidate, Mission, WorldState, new_id


class HumanizeMission:
    """The inner fixed pipeline for one package candidate."""

    def __init__(self, world: WorldState, mission: Mission, agents: AgentFactory):
        self.world, self.mission, self.agents = world, mission, agents

    def run(self) -> dict[str, Any]:
        self.mission.status = "ACTIVE"
        contract = MissionContract.create(self.mission.package, fence_version=self.world.fence_versions["abi"])
        self.mission.mission_contract_ref = contract.contract_hash
        candidate = Candidate(new_id("candidate"), self.mission.mission_id)
        self.world.candidates.append(candidate)
        work = self.agents.client.create({"project": "lda", "run_id": self.world.run_id,
            "life_cycle": str(self.world.life_cycle), "mission_id": self.mission.mission_id,
            "candidate_id": candidate.candidate_id, "role": "candidate-work", "template": "lda-base-lda-hm-as-prod-20260825-v12", "lease_id": new_id("lease")})
        configure = self.agents.client.command(work, "./configure && cmake --build build", background=False)
        local_verify = self.agents.client.command(work, "ctest --test-dir build", background=False)
        manager = self.agents.spec(run_id=self.world.run_id, life_cycle_id=str(self.world.life_cycle),
                                   mission_id=self.mission.mission_id, candidate_id=candidate.candidate_id,
                                   role="Mission Planner", independence_group="planner")
        self.agents.create(manager)
        self.agents.run(manager, f"Plan the bounded mission for package {self.mission.package}; return JSON only.")
        builder = self.agents.spec(run_id=self.world.run_id, life_cycle_id=str(self.world.life_cycle),
                                   mission_id=self.mission.mission_id, candidate_id=candidate.candidate_id,
                                   role="Builder", independence_group="builder")
        self.agents.create(builder)
        self.agents.run(builder, f"Build and locally verify candidate {candidate.candidate_id}; return JSON only.")
        reviewer = self.agents.spec(run_id=self.world.run_id, life_cycle_id=str(self.world.life_cycle),
                                    mission_id=self.mission.mission_id, candidate_id=candidate.candidate_id,
                                    role="Reviewer", independence_group="reviewer")
        self.agents.create(reviewer)
        self.agents.run(reviewer, "Review the candidate independently; return JSON only.")
        manifest = FenceManifest(self.mission.package, f"lib{self.mission.package}.so.1", ("api_entry",), ("LIB_1.0",), (f"{self.mission.package}.h",), install_paths=(f"/usr/lib/lib{self.mission.package}.so.1",))
        judge = CleanJudge(CompatibilityFence(manifest))
        judge_box = self.agents.client.create({"project": "lda", "run_id": self.world.run_id,
            "life_cycle": str(self.world.life_cycle), "mission_id": self.mission.mission_id,
            "candidate_id": candidate.candidate_id, "role": "judge", "template": "lda-judge", "lease_id": new_id("lease")})
        self.agents.client.command(judge_box, "lda-judge --clean", background=False)
        judge_result = judge.run({"manifest": {"soname": manifest.soname, "symbols": manifest.symbols,
            "symbol_versions": manifest.symbol_versions, "headers": manifest.headers,
            "install_paths": manifest.install_paths, "package_install": True, "rollback": True}},
            anti_cheat=AntiCheat().inspect({}))
        benchmark_result = self._read_benchmarks(work)
        benchmark_result.update({
            "build_exit_code": configure.get("exit_code"),
            "local_verify_exit_code": local_verify.get("exit_code"),
            "build_passed": configure.get("exit_code") == 0,
            "local_verify_passed": local_verify.get("exit_code") == 0,
        })
        if not benchmark_result["build_passed"] or not benchmark_result["local_verify_passed"]:
            benchmark_result["accepted"] = False
            benchmark_result["invalid"] = True
            benchmark_result["reason"] = "build_or_local_verify_failed"
        candidate.fence_passed = judge_result["fence_passed"]
        candidate.judge_status = "PASS" if judge_result["valid"] else "REJECT"
        candidate.micro_speedup = benchmark_result["micro_speedup"]
        candidate.micro_ci_lower = benchmark_result["micro_ci_lower"]
        candidate.e2e_speedup = benchmark_result["e2e_speedup"]
        self.mission.attempts += 1
        self.mission.last_outcome = "SUCCESS_SYSTEM" if judge_result["valid"] else "ABI_FAILURE"
        self.mission.status = "SUCCEEDED" if judge_result["valid"] else "REJECTED"
        self.agents.client.kill(work)
        self.agents.client.kill(judge_box)
        self.agents.release(manager)
        self.agents.release(builder)
        self.agents.release(reviewer)
        return {"contract": contract.dump(), "candidate": candidate, "judge": judge_result, "benchmark": benchmark_result,
                "sandboxes": {"work": work.sandbox_id, "judge": judge_box.sandbox_id}}

    def _read_benchmarks(self, work) -> dict[str, Any]:
        """Only accept benchmark evidence produced inside the candidate sandbox."""
        try:
            micro = json.loads(self.agents.client.filesystem_read(work, "/workspace/benchmarks/micro.json"))
            e2e = json.loads(self.agents.client.filesystem_read(work, "/workspace/benchmarks/e2e.json"))
            baseline = micro["baseline"]
            candidate = micro["candidate"]
            e2e_values = e2e["workloads"]
            micro_result = BenchmarkRunner().measure(baseline, candidate, kind="micro")
            portfolio = BenchmarkRunner().portfolio(e2e_values)
            return {
                "micro_speedup": micro_result.get("speedup", 0.0),
                "micro_ci_lower": micro_result.get("ci_lower", 0.0),
                "e2e_speedup": portfolio.get("geomean_speedup", 0.0),
                "improved_workloads": portfolio.get("improved_workloads", 0),
                "invalid": bool(micro_result.get("invalid") or portfolio.get("invalid")),
                "accepted": bool(micro_result.get("accepted") and not portfolio.get("invalid")),
                "micro": micro_result,
                "portfolio": portfolio,
                "evidence_refs": ["/workspace/benchmarks/micro.json", "/workspace/benchmarks/e2e.json"],
            }
        except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
            return {"invalid": True, "accepted": False, "reason": f"missing_or_invalid_benchmark_evidence: {exc}",
                    "micro_speedup": 0.0, "micro_ci_lower": 0.0, "e2e_speedup": 0.0,
                    "improved_workloads": 0, "evidence_refs": []}
