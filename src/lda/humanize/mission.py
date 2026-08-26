from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from lda.agents.factory import AgentFactory
from lda.benchmarks.canary import CANARY_PACKAGES, CanaryBenchmarkRunner, upload_source_snapshot
from lda.benchmarks.runner import BenchmarkRunner
from lda.fences.abi import CompatibilityFence, FenceManifest
from lda.judge.anti_cheat import AntiCheat
from lda.judge.canary import CleanCanaryJudge, SPECS as JUDGE_SPECS
from lda.judge.clean import CleanJudge
from lda.missions.contract import MissionContract
from lda.models import Candidate, Mission, WorldState, new_id


class HumanizeMission:
    """The inner fixed pipeline for one package candidate."""

    def __init__(self, world: WorldState, mission: Mission, agents: AgentFactory):
        self.world, self.mission, self.agents = world, mission, agents

    def _run_agent(self, spec, prompt: str) -> dict[str, Any]:
        """Run advisory Codex work with a bounded transport lifetime.

        Builder/Reviewer results are never used as Judge evidence.  A provider
        stall is recorded and the deterministic build/fence/benchmark path
        remains responsible for acceptance.
        """
        if os.environ.get("LDA_SKIP_MISSION_ADVISORY") == "1":
            return {"role": spec.role, "status": "advisory_skipped_by_controller"}
        try:
            return self.agents.run(spec, prompt)
        except Exception as exc:
            return {"role": spec.role, "error": str(exc), "status": "agent_failure"}

    def run(self) -> dict[str, Any]:
        self.mission.status = "ACTIVE"
        contract = MissionContract.create(self.mission.package, fence_version=self.world.fence_versions["abi"])
        self.mission.mission_contract_ref = contract.contract_hash
        candidate = next((item for item in reversed(self.world.candidates)
                          if item.mission_id == self.mission.mission_id
                          and item.status not in {"ACCEPTED", "REJECTED"}), None)
        if candidate is None:
            candidate = Candidate(new_id("candidate"), self.mission.mission_id)
            self.world.candidates.append(candidate)
        candidate.status = "ACTIVE"
        work = self.agents.client.create({"project": "lda", "run_id": self.world.run_id,
            "life_cycle": str(self.world.life_cycle), "mission_id": self.mission.mission_id,
            "candidate_id": candidate.candidate_id, "role": "candidate-work", "template": "lda-base-lda-hm-as-prod-20260825-v12", "lease_id": new_id("lease")})
        canary_runner = CanaryBenchmarkRunner(self.agents.client)
        build_evidence = None
        candidate_root = ""
        candidate_debs: dict[str, str] = {}
        if self.mission.package in CANARY_PACKAGES:
            # Every canary starts from the pinned source bundle. The upload and
            # hash verification happen inside the disposable candidate sandbox.
            repo_root = Path(__file__).resolve().parents[3]
            configured_root = self.world.qualification.get("source_snapshot_root") or os.environ.get("LDA_SOURCE_SNAPSHOT_ROOT")
            snapshot_candidates = [
                Path(configured_root).expanduser() if configured_root else None,
                repo_root / "source_snapshot",
                repo_root / ".campaign-input" / "source-snapshot",
                repo_root / ".campaign-input" / "source_snapshot",
            ]
            snapshot_root = next(
                (str(candidate) for candidate in snapshot_candidates
                 if candidate is not None and (candidate / "20260825T000000Z" / "SHA256SUMS").is_file()),
                str(repo_root / "source_snapshot"),
            )
            try:
                # Qualification uploads and hashes the complete pinned bundle.
                # Candidate sandboxes receive the manifest and fetch the exact
                # source version from the same fixed snapshot, verifying each
                # file hash locally to avoid a large gateway filesystem RPC.
                source_evidence = upload_source_snapshot(
                    self.agents.client, work, snapshot_root,
                    include_payload=self.mission.package == "libsoup-3.0-0",
                )
                build_evidence = canary_runner.build_candidate(work, self.mission.package)
                if build_evidence.get("passed"):
                    # A source build emits dev/docs/debug siblings. Extract the
                    # exact binary package under test, never the first listing.
                    artifact = build_evidence.get("target_artifact") or next((item for item in build_evidence["artifacts"]
                                     if Path(item).name.startswith(self.mission.package + "_")), None)
                    dev_package = JUDGE_SPECS[self.mission.package].dev_package
                    dev_artifact = next((item for item in build_evidence["artifacts"]
                                         if Path(item).name.startswith(dev_package + "_")), None)
                    if artifact is None:
                        build_evidence["passed"] = False
                        build_evidence["reason"] = "target_binary_deb_missing"
                        artifact = ""
                    elif dev_artifact is None:
                        build_evidence["passed"] = False
                        build_evidence["reason"] = "target_dev_deb_missing"
                    else:
                        candidate_debs = {"runtime": artifact, "dev": dev_artifact}
                    candidate_root = "/workspace/candidate-root" if artifact else ""
                    if artifact:
                        extract = self.agents.client.command(work, f"rm -rf {candidate_root} && mkdir -p {candidate_root} && dpkg-deb -x {artifact} {candidate_root}")
                        build_evidence["extract_exit_code"] = extract.get("exit_code")
                        build_evidence["candidate_root"] = candidate_root
                        if extract.get("exit_code") != 0:
                            build_evidence["passed"] = False
                            build_evidence["reason"] = "candidate_deb_extract_failed"
                build_evidence["source_snapshot"] = source_evidence
            except (FileNotFoundError, OSError, RuntimeError, ValueError) as exc:
                build_evidence = {"passed": False, "reason": f"canary_source_or_build_failed:{exc}", "artifacts": []}
            configure = {"exit_code": 0 if build_evidence.get("passed") else 1,
                         "stdout": "", "stderr": build_evidence.get("reason", "")}
            local_verify = self.agents.client.command(work, "test -n '" + (candidate_root or "") + "'", background=False, timeout=60)
        else:
            configure = self.agents.client.command(work, "./configure && cmake --build build", background=False)
            local_verify = self.agents.client.command(work, "ctest --test-dir build", background=False)
        manager = self.agents.spec(run_id=self.world.run_id, life_cycle_id=str(self.world.life_cycle),
                                   mission_id=self.mission.mission_id, candidate_id=candidate.candidate_id,
                                   role="Mission Planner", independence_group="planner", timeout_seconds=180)
        self.agents.create(manager)
        self._run_agent(manager, f"Plan the bounded mission for package {self.mission.package}; return JSON only.")
        builder = self.agents.spec(run_id=self.world.run_id, life_cycle_id=str(self.world.life_cycle),
                                   mission_id=self.mission.mission_id, candidate_id=candidate.candidate_id,
                                   role="Builder", independence_group="builder", timeout_seconds=180)
        self.agents.create(builder)
        self._run_agent(builder, f"Build and locally verify candidate {candidate.candidate_id}; return JSON only.")
        reviewer = self.agents.spec(run_id=self.world.run_id, life_cycle_id=str(self.world.life_cycle),
                                    mission_id=self.mission.mission_id, candidate_id=candidate.candidate_id,
                                    role="Reviewer", independence_group="reviewer", timeout_seconds=180)
        self.agents.create(reviewer)
        self._run_agent(reviewer, "Review the candidate independently; return JSON only.")
        judge_metadata = {"project": "lda", "run_id": self.world.run_id,
            "life_cycle": str(self.world.life_cycle), "mission_id": self.mission.mission_id,
            "candidate_id": candidate.candidate_id, "lease_id": new_id("lease")}
        if self.mission.package in CANARY_PACKAGES:
            if not candidate_debs:
                judge_box = self.agents.client.create({**judge_metadata, "role": "judge", "template": "lda-judge-v4-20260826"})
                judge_result = {"valid": False, "fence_passed": False, "checks": {},
                                "failure_category": "JUDGE_EVIDENCE_INVALID",
                                "reason": "runtime_and_dev_candidate_debs_required",
                                "evidence_refs": [], "confidence": 1.0}
            else:
                judge_result, judge_box = CleanCanaryJudge(self.agents.client).run(
                    work=work, package=self.mission.package,
                    candidate_debs=candidate_debs, metadata=judge_metadata)
        else:
            # Generic packages remain fail-closed until their package-specific
            # immutable manifest and clean Judge adapter have been qualified.
            manifest = FenceManifest(self.mission.package, "")
            judge = CleanJudge(CompatibilityFence(manifest))
            judge_box = self.agents.client.create({**judge_metadata, "role": "judge", "template": "lda-judge-v4-20260826"})
            judge_result = judge.run({}, self_test=False, reverse_dependencies=False,
                                     anti_cheat=AntiCheat().inspect({}))
        if self.mission.package in CANARY_PACKAGES:
            # The canary harness runs in the candidate E2B sandbox and records
            # measured baseline/candidate samples. A missing candidate root is
            # intentionally a measured no-change result, never a claimed gain.
            if not candidate_root:
                benchmark_result = {"invalid": True, "accepted": False,
                                    "reason": "missing_candidate_artifact",
                                    "micro_speedup": 0.0, "micro_ci_lower": 0.0,
                                    "e2e_speedup": 0.0, "improved_workloads": 0,
                                    "evidence_refs": []}
            else:
                benchmark_result = canary_runner.run(work, self.mission.package, candidate_root=candidate_root)
        else:
            benchmark_result = self._read_benchmarks(work)
        benchmark_result.update({
            "build_exit_code": configure.get("exit_code"),
            "local_verify_exit_code": local_verify.get("exit_code"),
            "build_passed": configure.get("exit_code") == 0,
            "local_verify_passed": local_verify.get("exit_code") == 0,
        })
        if build_evidence is not None:
            benchmark_result["build_evidence"] = build_evidence
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
        accepted = bool(judge_result["valid"] and benchmark_result.get("accepted") is True
                        and benchmark_result.get("invalid") is not True)
        if accepted:
            self.mission.last_outcome = "SUCCESS_SYSTEM"
            self.mission.status = "SUCCEEDED"
            candidate.status = "ACCEPTED"
        elif not judge_result["valid"]:
            self.mission.last_outcome = judge_result.get("failure_category", "ABI_FAILURE")
            self.mission.status = "REJECTED"
            candidate.status = "REJECTED"
        else:
            self.mission.last_outcome = "BENCHMARK_INVALID" if benchmark_result.get("invalid") else "NO_OPTIMIZATION_SPACE"
            self.mission.status = "QUEUED" if self.mission.attempts < self.mission.max_attempts else "REJECTED"
            candidate.status = "ACTIVE" if self.mission.status == "QUEUED" else "REJECTED"
        self.agents.client.kill(work)
        self.agents.client.kill(judge_box)
        self.agents.release(manager)
        if self.mission.status in {"SUCCEEDED", "REJECTED", "STOPPED"}:
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
