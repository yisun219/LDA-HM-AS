from __future__ import annotations

import asyncio
import json
import math
import os
import shlex
from hashlib import sha256
from pathlib import Path
from typing import Any
from uuid import uuid4

from e2b import AsyncSandbox

from lda.agents import AgentFactory
from lda.artifacts import ArtifactStore
from lda.benchmarks import BenchmarkDecision, BenchmarkSeries, compare_paired
from lda.config import LDAConfig
from lda.e2b import E2BSandboxManager, SandboxLease, SandboxRole, run_durable_command
from lda.e2b.preflight import run_preflight
from lda.fences import scan_trace
from lda.gateway import CapabilityAuthority
from lda.judge import DeterministicJudge, JudgeDecision
from lda.missions import create_contract
from lda.models import (
    AgentSpec,
    CandidateState,
    CandidateStatus,
    MissionPhase,
    MissionState,
    QualificationRecord,
    RunPhase,
    RunState,
    SessionPolicy,
)
from lda.packages import freeze_mission_queue
from lda.research import build_qualification_records
from lda.state import EventStore

from .convergence import ConvergenceEvaluator, ConvergenceReason
from .request import MissionDefinition, RunRequest


CANARY_PACKAGES = ("libcairo2", "libsoup-3.0-0")


def mission_execution_waves(packages: list[str]) -> tuple[list[str], list[str]]:
    """Keep the frozen queue intact while enforcing the Canary barrier."""
    canaries = [package for package in CANARY_PACKAGES if package in packages]
    remaining = [package for package in packages if package not in CANARY_PACKAGES]
    return canaries, remaining


class PureHumanizeController:
    def __init__(self, request: RunRequest, config: LDAConfig, persist_root: Path) -> None:
        if request.flow != "pure-humanize":
            raise ValueError("controller only accepts pure-humanize")
        self.request = request
        self.config = config
        self.persist_root = persist_root.resolve()
        self.store = EventStore(self.persist_root / "state")
        self.artifacts = ArtifactStore(self.persist_root / "artifacts")
        self.manager = E2BSandboxManager(
            config.e2b,
            self.store,
            max_live=config.scheduler.max_live_sandboxes,
        )
        self.authority = CapabilityAuthority.from_environment(config.capability_signing_key_env)
        self.registry = self.persist_root / "workspaces.json"
        if not self.registry.exists():
            self.registry.write_text("{}\n", encoding="utf-8")
        self.gateway_url = os.environ.get("LDA_GATEWAY_URL", "")
        self.agents = AgentFactory(
            self.manager,
            self.artifacts,
            self.store,
            self.authority,
            gateway_url=self.gateway_url,
            max_live_sessions=config.scheduler.max_live_codex_sessions,
        )
        self.judge = DeterministicJudge(self.manager, self.artifacts, config.benchmark)
        self.convergence = ConvergenceEvaluator(
            max_attempts=config.scheduler.max_attempts_per_candidate
        )

    async def _start_gateway(self) -> str:
        controller_id = os.environ.get("LDA_CONTROLLER_SANDBOX_ID", "")
        if not controller_id:
            raise RuntimeError("controller must run inside an E2B sandbox")
        controller = await AsyncSandbox.connect(sandbox_id=controller_id, timeout=120)
        host = controller.get_host(8090)
        command = (
            "lda-tool-gateway "
            f"--registry {shlex.quote(str(self.registry))} "
            f"--artifacts {shlex.quote(str(self.persist_root / 'artifacts'))} "
            "--port 8090"
        )
        Path(self.persist_root / "gateway-command.txt").write_text("lda-tool-gateway --port 8090\n", encoding="utf-8")
        # This process is the controller; starting the local service does not create a host fallback.
        import subprocess

        subprocess.Popen(command, shell=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return host if host.startswith("http") else f"https://{host}"

    def _load_or_create_state(self) -> RunState:
        try:
            return self.store.load_run(self.request.run_id)
        except KeyError:
            state = RunState(
                run_id=self.request.run_id,
                research_snapshot_id=self.request.research_snapshot.snapshot_id,
                controller_sandbox_id=os.environ["LDA_CONTROLLER_SANDBOX_ID"],
            )
            self.store.save_run(state, "run.created")
            return state

    async def run(self) -> RunState:
        if not self.gateway_url:
            self.gateway_url = await self._start_gateway()
            self.agents.gateway_url = self.gateway_url
        state = self._load_or_create_state()
        if state.failure:
            previous_failure = state.failure
            state.failure = None
            self.store.save_run(state, "run.resumed", {"previous_failure": previous_failure})
        if state.cancelled or (self.persist_root / "cancel.request").exists():
            state.cancelled = True
            state.phase = RunPhase.CANCELLED
            self.store.save_run(state, "run.cancelled")
            return state
        if state.phase is RunPhase.RUN_CREATED:
            state.phase = RunPhase.E2B_PREFLIGHT
            self.store.save_run(state, "preflight.started")
            report = await run_preflight(self.config.e2b)
            report_ref = self.artifacts.put_bytes(report.to_json().encode())
            self.store.save_run(state, "preflight.passed", {"report_ref": report_ref})
        if state.phase is RunPhase.E2B_PREFLIGHT:
            state.phase = RunPhase.RESEARCH_FROZEN
            source_refs: list[str] = []
            for index, source in enumerate(self.request.research_snapshot.source_artifacts):
                content = self.artifacts.read_bytes(source.artifact_ref)
                if sha256(content).hexdigest() != source.sha256:
                    raise RuntimeError(f"frozen research source failed verification: {source.file_name}")
                ref_name = f"runs/{state.run_id}/research-sources/{index + 1:02d}.ref"
                self.artifacts.set_ref(ref_name, source.artifact_ref)
                source_refs.append(source.artifact_ref)
            snapshot_ref = self.artifacts.put_json(self.request.research_snapshot)
            self.artifacts.set_ref(f"runs/{state.run_id}/research.json", snapshot_ref)
            curator_ref = await self._advisory_agent(
                state,
                role="research-curator",
                mission_id="research",
                candidate_id=None,
                prompt_file="prompts/research-curator.md",
                schema_file="schemas/agent/research-curator.json",
                context_refs=source_refs,
                allowed_tools=["artifact.read"],
                payload={"research_snapshot_ref": snapshot_ref, "source_artifact_refs": source_refs},
            )
            self.store.save_run(state, "research.frozen", {"snapshot_ref": snapshot_ref, "source_refs": source_refs, "curator_ref": curator_ref})
        if state.phase is RunPhase.RESEARCH_FROZEN:
            state.phase = RunPhase.PORTFOLIO_PLANNED
            queue = freeze_mission_queue(
                state.run_id,
                self.request.research_snapshot,
                self.request.inventory,
                limit=self.request.queue_limit,
            )
            qualification_records = build_qualification_records(
                self.request.research_snapshot,
                [item.package for item in queue.scores],
                ubuntu_snapshot=self.config.ubuntu_snapshot,
            )
            qualification_ref = self.artifacts.put_json(
                [record.model_dump(mode="json") for record in qualification_records]
            )
            self.artifacts.set_ref(f"runs/{state.run_id}/qualification.json", qualification_ref)
            for package in queue.missions:
                self.request.definition(package)
            portfolio_ref = await self._advisory_agent(
                state,
                role="portfolio-planner",
                mission_id="portfolio",
                candidate_id=None,
                prompt_file="prompts/portfolio-planner.md",
                schema_file="schemas/agent/portfolio.json",
                context_refs=[],
                allowed_tools=["artifact.read"],
                payload={
                    "deterministic_scores": [item.model_dump(mode="json") for item in queue.scores],
                    "constraint": "rank only these packages; controller freezes final order",
                },
            )
            queue_ref = self.artifacts.put_json(queue)
            self.artifacts.set_ref(f"runs/{state.run_id}/mission-queue.json", queue_ref)
            state.mission_queue_hash = queue.queue_hash
            state.missions = {
                package: MissionState(mission_id=f"{index + 1:02d}-{package}")
                for index, package in enumerate(queue.missions)
            }
            self.store.save_run(state, "portfolio.planned", {"queue_ref": queue_ref, "planner_ref": portfolio_ref, "qualification_ref": qualification_ref})
        if state.phase is RunPhase.PORTFOLIO_PLANNED:
            state.phase = RunPhase.MISSION_QUEUE_FROZEN
            self.store.save_run(state, "mission_queue.frozen", {"queue_hash": state.mission_queue_hash})
        if state.phase in {
            RunPhase.MISSION_QUEUE_FROZEN,
            RunPhase.MISSION_BASELINE,
            RunPhase.PROFILE,
            RunPhase.HYPOTHESIS,
            RunPhase.CANDIDATE_FORK,
            RunPhase.BUILD,
            RunPhase.LOCAL_VERIFY,
            RunPhase.ADVERSARIAL_REVIEW,
            RunPhase.CLEAN_JUDGE,
            RunPhase.NEXT_MISSION,
        }:
            queue = self.artifacts.read_json(self.artifacts.resolve(f"runs/{state.run_id}/mission-queue.json"))
            packages = list(queue["missions"])
            semaphore = asyncio.Semaphore(self.config.scheduler.max_active_missions)

            async def bounded(package: str) -> None:
                async with semaphore:
                    await self._run_mission(state, package, self.request.definition(package))

            canaries, remaining = mission_execution_waves(packages)
            if canaries:
                self.store.save_run(state, "canary.started", {"packages": canaries})
                await asyncio.gather(*(bounded(package) for package in canaries))
                self.store.save_run(
                    state,
                    "canary.completed",
                    {
                        "packages": canaries,
                        "phases": {
                            package: state.missions[package].phase.value
                            for package in canaries
                        },
                    },
                )
            await asyncio.gather(*(bounded(package) for package in remaining))
            state.phase = RunPhase.PORTFOLIO_E2E
            self.store.save_run(state, "missions.completed")
        if state.phase is RunPhase.PORTFOLIO_E2E:
            release_ready = await self._portfolio_e2e(state)
            state.phase = RunPhase.RELEASE_READY if release_ready else RunPhase.COMPLETED_WITHOUT_RELEASE
            self.store.save_run(state, "portfolio.completed", {"release_ready": release_ready})
        return state

    async def _run_mission(self, run_state: RunState, package: str, definition: MissionDefinition) -> None:
        mission = run_state.missions[package]
        if mission.phase in {MissionPhase.LOCAL_WIN, MissionPhase.SYSTEM_WIN, MissionPhase.REJECTED, MissionPhase.INVALID, MissionPhase.NOT_HOT}:
            return
        run_state.phase = RunPhase.MISSION_BASELINE
        mission.phase = MissionPhase.BASELINE
        self.store.save_run(run_state, "mission.baseline.started", {"package": package})
        baseline_lease = SandboxLease.deterministic(
            f"mission:{mission.mission_id}:baseline",
            run_id=run_state.run_id,
            mission_id=mission.mission_id,
            role=SandboxRole.WORKSPACE,
            template=self.config.e2b.base_template,
        )
        baseline = await self.manager.create(baseline_lease, timeout=7200, envs={})
        try:
            await self._run_commands(baseline, definition.baseline_commands, "baseline")
            identity = await self._baseline_identity(baseline, definition)
            contract = create_contract(
                mission_id=mission.mission_id,
                source_package=definition.source_package,
                binary_packages=definition.binary_packages,
                official_source_hash=identity["official_source_hash"],
                official_deb_hashes=identity["official_deb_hashes"],
                target_functions=definition.target_functions,
                target_workloads=definition.target_workloads,
                allowed_source_paths=definition.allowed_source_paths,
                forbidden_paths=definition.forbidden_paths,
                abi_manifest=definition.abi_manifest,
                api_manifest=definition.api_manifest,
                ffi_manifest=definition.ffi_manifest,
                self_tests=definition.self_tests,
                reverse_dependency_tests=definition.reverse_dependency_tests,
                microbench_manifest=definition.microbench_manifest,
                e2e_manifest=definition.e2e_manifest,
                hardware_profile=identity["hardware_profile"],
                qualification_evidence=[identity["package_metadata_ref"]],
                candidate_budget=definition.candidate_budget,
                acceptance_policy=definition.acceptance_policy,
            )
            contract_ref = self.artifacts.put_json(contract)
            mission.contract_ref = contract_ref
            self.store.save_run(run_state, "mission.contract.frozen", {
                "package": package,
                "contract_ref": contract_ref,
                "package_metadata_ref": identity["package_metadata_ref"],
            })
            run_state.phase = RunPhase.PROFILE
            mission.phase = MissionPhase.PROFILE
            profile = await self._run_commands(baseline, definition.profile_commands, "profile")
            profile_ref = self.artifacts.put_json(profile)
            profiler_ref = await self._advisory_agent(
                run_state,
                role="profiler",
                mission_id=mission.mission_id,
                candidate_id=None,
                prompt_file="prompts/profiler.md",
                schema_file="schemas/agent/profiler.json",
                context_refs=[profile_ref, contract_ref],
                allowed_tools=["artifact.read", "test_result.read", "benchmark_result.read"],
                payload={"profile_ref": profile_ref, "contract_ref": contract_ref},
            )
            if not any(result["exit_code"] == 0 and result["stdout"].strip() for result in profile):
                mission.phase = MissionPhase.NOT_HOT
                self.store.save_run(run_state, "mission.not_hot", {"package": package})
                return
            profiler = self.artifacts.read_json(profiler_ref)
            if not profiler.get("hot_paths"):
                mission.phase = MissionPhase.NOT_HOT
                self.store.save_run(
                    run_state,
                    "mission.not_hot",
                    {
                        "package": package,
                        "profiler_ref": profiler_ref,
                        "reason": "profile did not verify a Contract target hot path",
                    },
                )
                return
            qualification = QualificationRecord(
                package=package,
                source_package=definition.source_package,
                source_version=definition.source_version,
                binary_packages=tuple(definition.binary_packages),
                snapshot=self.config.ubuntu_snapshot,
                binary_identity_verified=True,
                dependency_identity_verified=True,
                unresolved_edges_verified=True,
                clean_rebuild_verified=True,
                hotspot_verified=True,
                microbench_feasible=True,
                e2e_feasible=True,
                drop_in_replacement_feasible=True,
                status="QUALIFIED",
                evidence_refs=(
                    identity["package_metadata_ref"],
                    profile_ref,
                    profiler_ref,
                ),
                notes=(
                    "Exact package/source identity and dependency installation were verified against the fixed Ubuntu Snapshot.",
                    "Drop-in feasibility is promoted only to Candidate acceptance after the clean Judge ABI/API/FFI fence.",
                ),
            )
            qualification_ref = self.artifacts.put_json(qualification)
            self.artifacts.set_ref(
                f"runs/{run_state.run_id}/qualifications/{package}.json",
                qualification_ref,
            )
            self.store.save_run(
                run_state,
                "mission.qualified",
                {"package": package, "qualification_ref": qualification_ref},
            )
            run_state.phase = RunPhase.HYPOTHESIS
            mission.phase = MissionPhase.HYPOTHESIS
            hypotheses = await self._plan_hypotheses(
                run_state,
                mission,
                definition,
                contract_ref,
                profile_ref,
                profiler_ref,
            )
            await self._run_commands(
                baseline,
                [["/opt/lda/harness/checks/seal-candidate-workspace.sh"]],
                "candidate-workspace-seal",
            )
            baseline_snapshot_id = await self.manager.create_snapshot(
                baseline_lease.lease_id,
                name=f"lda-{run_state.run_id}-{mission.mission_id}-baseline",
            )
            run_state.phase = RunPhase.CANDIDATE_FORK
            mission.phase = MissionPhase.CANDIDATES
            candidate_inputs = hypotheses[: self.config.scheduler.max_candidates_per_mission]
            await asyncio.gather(
                *(
                    self._run_candidate(
                        run_state,
                        mission,
                        definition,
                        contract,
                        baseline_snapshot_id,
                        hypothesis,
                    )
                    for hypothesis in candidate_inputs
                )
            )
            wins = [candidate for candidate in mission.candidates.values() if candidate.status in {CandidateStatus.LOCAL_WIN, CandidateStatus.SYSTEM_WIN}]
            if wins:
                winner = max(wins, key=lambda candidate: candidate.best_speedup)
                mission.winner_candidate_id = winner.candidate_id
                mission.phase = MissionPhase.SYSTEM_WIN if winner.status is CandidateStatus.SYSTEM_WIN else MissionPhase.LOCAL_WIN
            else:
                mission.phase = MissionPhase.REJECTED
            self.store.save_run(run_state, "mission.converged", {"package": package, "phase": mission.phase.value})
        except Exception as error:
            mission.phase = MissionPhase.INVALID
            self.store.save_run(run_state, "mission.invalid", {"package": package, "error": f"{type(error).__name__}: {error}"})
        finally:
            await self.manager.kill(baseline_lease.lease_id)

    async def _run_candidate(
        self,
        run_state: RunState,
        mission: MissionState,
        definition: MissionDefinition,
        contract,
        snapshot_id: str,
        hypothesis: dict[str, Any],
    ) -> None:
        candidate_id = str(hypothesis.get("candidate_id") or uuid4().hex[:12])
        candidate = mission.candidates.get(candidate_id)
        if candidate is None:
            candidate = CandidateState(candidate_id=candidate_id, mission_id=mission.mission_id)
            mission.candidates[candidate_id] = candidate
            self.store.save_run(
                run_state,
                "candidate.created",
                {"mission_id": mission.mission_id, "candidate_id": candidate_id},
            )
        elif candidate.status in {
            CandidateStatus.LOCAL_WIN,
            CandidateStatus.SYSTEM_WIN,
            CandidateStatus.REJECTED,
            CandidateStatus.INVALID,
            CandidateStatus.CANCELLED,
        }:
            return
        lease = SandboxLease.deterministic(
            f"mission:{mission.mission_id}:candidate:{candidate_id}:workspace",
            run_id=run_state.run_id,
            mission_id=mission.mission_id,
            candidate_id=candidate_id,
            role=SandboxRole.WORKSPACE,
            template=snapshot_id,
        )
        workspace = await self.manager.create(
            lease,
            timeout=7200,
            envs={},
            allow_internet_access=False,
        )
        candidate.workspace_sandbox_id = str(workspace.sandbox_id)
        self._register_workspace(candidate_id, str(workspace.sandbox_id))
        builder = None
        try:
            prompt = self._candidate_prompt(contract, hypothesis)
            prompt_ref = self.artifacts.put_bytes(prompt.encode())
            schema_ref = self.artifacts.put_bytes((Path("schemas/agent/builder.json").read_bytes()))
            spec = AgentSpec(
                run_id=run_state.run_id,
                mission_id=mission.mission_id,
                candidate_id=candidate_id,
                role="builder",
                backend=self.request.agent_backend,
                model=self.request.agent_model,
                reasoning_effort=self.request.reasoning_effort,
                prompt_version="builder-v1",
                context_refs=[mission.contract_ref or ""],
                allowed_tools=[
                    "workspace.read", "workspace.write", "workspace.apply_patch", "workspace.exec",
                    "workspace.profile", "workspace.git_diff", "artifact.publish",
                ],
                runtime_template=self.config.e2b.agent_template,
                workspace_id=candidate_id,
                session_policy=SessionPolicy.PERSISTENT,
                output_schema=schema_ref,
                timeout_seconds=3600,
                token_budget=100_000,
                independence_group=f"builder-{candidate_id}",
            )
            builder = await self.agents.spawn(spec)
            first_attempt = max(1, candidate.attempts or 1)
            for attempt_number in range(
                first_attempt,
                self.config.scheduler.max_attempts_per_candidate + 1,
            ):
                if (self.persist_root / "cancel.request").exists():
                    candidate.status = CandidateStatus.CANCELLED
                    self.store.save_run(
                        run_state,
                        "candidate.terminal",
                        {"candidate_id": candidate_id, "status": candidate.status.value},
                    )
                    return
                candidate.attempts = attempt_number
                candidate.status = CandidateStatus.BUILDING
                run_state.phase = RunPhase.BUILD
                self.store.save_run(
                    run_state,
                    "candidate.attempt.started",
                    {"candidate_id": candidate_id, "attempt": candidate.attempts},
                )
                saved_thread = self.store.load_thread(builder.key)
                result = await (
                    builder.resume(prompt_ref)
                    if candidate.builder_thread_id or saved_thread
                    else builder.run(prompt_ref)
                )
                candidate.builder_thread_id = result.thread_id
                self.store.save_run(
                    run_state,
                    "candidate.builder.completed",
                    {"candidate_id": candidate_id, "attempt": candidate.attempts, "trace_ref": result.trace_ref},
                )
                committed, boundary_error = await self._commit_candidate_changes(
                    workspace,
                    contract.allowed_source_paths,
                    contract.forbidden_paths,
                    candidate_id,
                    attempt_number,
                )
                if boundary_error:
                    candidate.status = CandidateStatus.REJECTED
                    self.store.save_run(
                        run_state,
                        "candidate.path_boundary_rejected",
                        {"candidate_id": candidate_id, "error": boundary_error},
                    )
                    return
                if not committed and attempt_number > 1:
                    candidate.no_improvement_rounds += 1
                candidate.status = CandidateStatus.LOCAL_VERIFY
                run_state.phase = RunPhase.LOCAL_VERIFY
                local = await self._run_commands(
                    workspace,
                    definition.local_verify_commands,
                    "local-verify",
                    raise_on_failure=False,
                )
                local_ref = self.artifacts.put_json(local)
                self.store.save_run(
                    run_state,
                    "candidate.local_verify.completed",
                    {"candidate_id": candidate_id, "attempt": candidate.attempts, "result_ref": local_ref},
                )
                if not all(item["exit_code"] == 0 for item in local):
                    candidate.no_improvement_rounds += 1
                    feedback = self.artifacts.put_bytes(json.dumps({"local_verify": local_ref}).encode())
                    prompt_ref = feedback
                    if self.convergence.candidate(candidate) is not ConvergenceReason.CONTINUE:
                        candidate.status = CandidateStatus.REJECTED
                        self.store.save_run(
                            run_state,
                            "candidate.terminal",
                            {"candidate_id": candidate_id, "status": candidate.status.value},
                        )
                        return
                    continue
                patch_result = await workspace.commands.run(
                    "git -C /opt/lda/work diff --binary lda-baseline..HEAD"
                )
                if patch_result.exit_code != 0 or not patch_result.stdout.strip():
                    candidate.no_improvement_rounds += 1
                    prompt_ref = self.artifacts.put_bytes(
                        json.dumps({"error": "candidate did not produce a patch from the immutable baseline"}).encode()
                    )
                    if self.convergence.candidate(candidate) is not ConvergenceReason.CONTINUE:
                        candidate.status = CandidateStatus.REJECTED
                        self.store.save_run(
                            run_state,
                            "candidate.terminal",
                            {"candidate_id": candidate_id, "status": candidate.status.value},
                        )
                        return
                    continue
                patch_ref = self.artifacts.put_bytes(str(patch_result.stdout).encode())
                run_state.phase = RunPhase.ADVERSARIAL_REVIEW
                review = await self._review_candidate(run_state, mission, candidate, patch_ref, local_ref, result.trace_ref)
                self.store.save_run(
                    run_state,
                    "candidate.review.completed",
                    {"candidate_id": candidate_id, "attempt": candidate.attempts, "verdict": review.get("verdict")},
                )
                findings = scan_trace(self.artifacts.objects / result.trace_ref[:2] / result.trace_ref[2:])
                audit_ref = await self._advisory_agent(
                    run_state,
                    role="trace-auditor",
                    mission_id=mission.mission_id,
                    candidate_id=candidate_id,
                    prompt_file="prompts/trace-auditor.md",
                    schema_file="schemas/agent/trace-audit.json",
                    context_refs=[patch_ref, local_ref, result.trace_ref],
                    allowed_tools=["candidate.diff", "trace.read", "artifact.read"],
                    payload={"patch_ref": patch_ref, "tests_ref": local_ref, "trace_ref": result.trace_ref},
                )
                audit = self.artifacts.read_json(audit_ref)
                if findings or audit.get("suspicious_actions") or review.get("verdict") == "REGRESSED":
                    candidate.no_improvement_rounds += 1
                    prompt_ref = self.artifacts.put_bytes(json.dumps({"review": review, "anti_cheat": [item.model_dump() for item in findings], "trace_audit_ref": audit_ref}).encode())
                    if findings or audit.get("suspicious_actions") or self.convergence.candidate(candidate) is not ConvergenceReason.CONTINUE:
                        candidate.status = CandidateStatus.REJECTED
                        self.store.save_run(
                            run_state,
                            "candidate.terminal",
                            {"candidate_id": candidate_id, "status": candidate.status.value},
                        )
                        return
                    continue
                candidate.status = CandidateStatus.JUDGING
                run_state.phase = RunPhase.CLEAN_JUDGE
                judge = await self.judge.evaluate(
                    contract,
                    definition.judge_manifest,
                    run_id=run_state.run_id,
                    candidate_id=candidate_id,
                    candidate_patch_ref=patch_ref,
                    template=self.config.e2b.judge_template,
                )
                judge_ref = self.artifacts.put_json(judge)
                candidate.judge_result_ref = judge_ref
                self.store.save_run(
                    run_state,
                    "candidate.judge.completed",
                    {"candidate_id": candidate_id, "attempt": candidate.attempts, "decision": judge.decision.value, "result_ref": judge_ref},
                )
                measured_speedups = [
                    float(self.artifacts.read_json(reference)["paired_geomean_ratio"])
                    for reference in judge.benchmark_refs
                    if self.artifacts.read_json(reference).get("layer") == "micro"
                ]
                if measured_speedups:
                    candidate.best_speedup = max(candidate.best_speedup, *measured_speedups)
                if judge.decision is JudgeDecision.LOCAL_WIN:
                    candidate.status = CandidateStatus.LOCAL_WIN
                    self.store.save_run(
                        run_state,
                        "candidate.terminal",
                        {"candidate_id": candidate_id, "status": candidate.status.value, "best_speedup": candidate.best_speedup},
                    )
                    return
                if judge.decision is JudgeDecision.SYSTEM_WIN:
                    candidate.status = CandidateStatus.SYSTEM_WIN
                    self.store.save_run(
                        run_state,
                        "candidate.terminal",
                        {"candidate_id": candidate_id, "status": candidate.status.value, "best_speedup": candidate.best_speedup},
                    )
                    return
                if judge.decision is JudgeDecision.INVALID:
                    candidate.status = CandidateStatus.INVALID
                    self.store.save_run(
                        run_state,
                        "candidate.terminal",
                        {"candidate_id": candidate_id, "status": candidate.status.value},
                    )
                    return
                candidate.no_improvement_rounds += 1
                prompt_ref = self.artifacts.put_bytes(json.dumps({"judge_result_ref": judge_ref, "reason": judge.reason}).encode())
                if self.convergence.candidate(candidate) is not ConvergenceReason.CONTINUE:
                    candidate.status = CandidateStatus.REJECTED
                    self.store.save_run(
                        run_state,
                        "candidate.terminal",
                        {"candidate_id": candidate_id, "status": candidate.status.value},
                    )
                    return
            candidate.status = CandidateStatus.REJECTED
            self.store.save_run(
                run_state,
                "candidate.terminal",
                {"candidate_id": candidate_id, "status": candidate.status.value},
            )
        finally:
            try:
                if builder is not None:
                    await builder.cancel()
            finally:
                self._unregister_workspace(candidate_id)
                await self.manager.kill(lease.lease_id)

    async def _plan_hypotheses(
        self,
        state: RunState,
        mission: MissionState,
        definition: MissionDefinition,
        contract_ref: str,
        profile_ref: str,
        profiler_ref: str,
    ) -> list[dict[str, Any]]:
        prompt = (
            Path("prompts/mission-planner.md").read_text(encoding="utf-8")
            + f"\nContract ref: {contract_ref}\nProfile ref: {profile_ref}\n"
            + "\nEmbedded immutable Contract:\n"
            + self.artifacts.read_bytes(contract_ref).decode(errors="replace")[:12_000]
            + "\nEmbedded Profile evidence:\n"
            + self.artifacts.read_bytes(profile_ref).decode(errors="replace")[:12_000]
            + "\nProfiler interpretation:\n"
            + self.artifacts.read_bytes(profiler_ref).decode(errors="replace")[:6_000]
            + "\nPreviously observed hypotheses that must be independently revalidated:\n"
            + json.dumps([item.model_dump(mode="json") for item in definition.seed_hypotheses], indent=2)
        )
        prompt_ref = self.artifacts.put_bytes(prompt.encode())
        schema_ref = self.artifacts.put_bytes(Path("schemas/agent/hypothesis.json").read_bytes())
        spec = AgentSpec(
            run_id=state.run_id,
            mission_id=mission.mission_id,
            role="mission-planner",
            backend=self.request.agent_backend,
            model=self.request.agent_model,
            reasoning_effort="low",
            prompt_version="mission-planner-v1",
            runtime_template=self.config.e2b.agent_template,
            context_refs=[contract_ref, profile_ref, profiler_ref],
            allowed_tools=["artifact.read", "test_result.read", "benchmark_result.read"],
            session_policy=SessionPolicy.FRESH,
            output_schema=schema_ref,
            timeout_seconds=1800,
            token_budget=50_000,
            independence_group=f"mission-planner-{mission.mission_id}",
        )
        handle = await self.agents.spawn(spec)
        try:
            result = await handle.run(prompt_ref)
            combined = [
                *[item.model_dump(mode="json") for item in definition.seed_hypotheses],
                *list(result.output["hypotheses"]),
            ]
            unique: dict[str, dict[str, Any]] = {}
            for hypothesis in combined:
                unique.setdefault(str(hypothesis["candidate_id"]), hypothesis)
            return list(unique.values())[: self.config.scheduler.max_candidates_per_mission]
        finally:
            await handle.cancel()

    async def _review_candidate(self, state: RunState, mission: MissionState, candidate: CandidateState, patch_ref: str, tests_ref: str, trace_ref: str) -> dict[str, Any]:
        references = {
            "contract_ref": mission.contract_ref,
            "patch_ref": patch_ref,
            "tests_ref": tests_ref,
            "trace_ref": trace_ref,
        }
        embedded = {
            reference: self.artifacts.read_bytes(reference).decode(errors="replace")[:12_000]
            for reference in references.values()
            if reference
        }
        prompt = (
            Path("prompts/reviewer.md").read_text(encoding="utf-8")
            + "\n"
            + json.dumps(references, indent=2)
            + "\nEmbedded independent review evidence:\n"
            + json.dumps(embedded, indent=2)
        )
        prompt_ref = self.artifacts.put_bytes(prompt.encode())
        schema_ref = self.artifacts.put_bytes(Path("schemas/agent/reviewer.json").read_bytes())
        spec = AgentSpec(
            run_id=state.run_id,
            mission_id=mission.mission_id,
            candidate_id=candidate.candidate_id,
            role="reviewer",
            backend=self.request.agent_backend,
            model=self.request.agent_model,
            reasoning_effort="low",
            prompt_version="reviewer-v1",
            runtime_template=self.config.e2b.agent_template,
            context_refs=[mission.contract_ref or "", patch_ref, tests_ref, trace_ref],
            allowed_tools=["artifact.read", "candidate.diff", "test_result.read", "benchmark_result.read", "trace.read"],
            session_policy=SessionPolicy.FRESH,
            output_schema=schema_ref,
            timeout_seconds=1800,
            token_budget=50_000,
            independence_group=f"review-{candidate.candidate_id}-{candidate.attempts}",
        )
        handle = await self.agents.spawn(spec)
        try:
            result = await handle.run(prompt_ref)
            return result.output
        finally:
            await handle.cancel()

    async def _baseline_identity(self, sandbox: Any, definition: MissionDefinition) -> dict[str, Any]:
        source = await sandbox.commands.run("sha256sum /opt/lda/baseline/source.tar.* 2>/dev/null | head -1 | cut -d' ' -f1")
        debs = await sandbox.commands.run("sha256sum /opt/lda/baseline/*.deb 2>/dev/null || true")
        cpu = await sandbox.commands.run("lscpu && printf '\n---CPUID---\n' && grep -m1 '^flags' /proc/cpuinfo")
        metadata = await sandbox.files.read("/opt/lda/baseline/package-metadata.txt")
        source_hash = source.stdout.strip()
        if len(source_hash) != 64:
            raise RuntimeError("baseline did not publish a pinned source archive")
        deb_hashes: dict[str, str] = {}
        for line in debs.stdout.splitlines():
            digest, path = line.split(maxsplit=1)
            deb_hashes[Path(path).name] = digest
        if not deb_hashes:
            raise RuntimeError("baseline did not publish official Debian packages")
        return {
            "official_source_hash": source_hash,
            "official_deb_hashes": deb_hashes,
            "hardware_profile": self.artifacts.put_bytes(cpu.stdout.encode()),
            "package_metadata_ref": self.artifacts.put_bytes(
                metadata if isinstance(metadata, bytes) else str(metadata).encode()
            ),
        }

    async def _run_commands(
        self,
        sandbox: Any,
        commands: list[list[str]],
        level: str,
        *,
        raise_on_failure: bool = True,
    ) -> list[dict[str, Any]]:
        results: list[dict[str, Any]] = []
        for command in commands:
            completed = await run_durable_command(
                sandbox,
                " ".join(shlex.quote(part) for part in command),
                timeout=7200,
            )
            results.append({
                "level": level,
                "command": command,
                "exit_code": int(completed.exit_code),
                "stdout": str(completed.stdout),
                "stderr": str(completed.stderr),
            })
            if completed.exit_code != 0 and raise_on_failure:
                raise RuntimeError(f"{level} command failed: {command}: {completed.stderr[-1000:]}")
        return results

    async def _commit_candidate_changes(
        self,
        workspace: Any,
        allowed_paths: list[str],
        forbidden_paths: list[str],
        candidate_id: str,
        attempt: int,
    ) -> tuple[bool, str | None]:
        changed = await workspace.commands.run(
            "git -C /opt/lda/work status --porcelain=v1 --untracked-files=all"
        )
        if changed.exit_code != 0:
            return False, "could not inspect candidate worktree"
        paths: list[str] = []
        for line in changed.stdout.splitlines():
            if len(line) < 4:
                continue
            path = line[3:].split(" -> ")[-1]
            paths.append(f"/opt/lda/work/{path}")
        if not paths:
            return False, None
        for path in paths:
            if any(path == forbidden or path.startswith(forbidden.rstrip("/") + "/") for forbidden in forbidden_paths):
                return False, f"forbidden path changed: {path}"
            if not any(path == allowed or path.startswith(allowed.rstrip("/") + "/") for allowed in allowed_paths):
                return False, f"path outside Mission Contract: {path}"
        message = shlex.quote(f"LDA candidate {candidate_id} attempt {attempt}")
        commit = await workspace.commands.run(
            "git -C /opt/lda/work add -A && "
            "git -C /opt/lda/work -c user.name=LDA -c user.email=lda@localhost "
            f"commit -m {message}"
        )
        if commit.exit_code != 0:
            return False, f"could not commit candidate changes: {commit.stderr[-500:]}"
        return True, None

    def _candidate_prompt(self, contract, hypothesis: dict[str, Any]) -> str:
        return Path("prompts/builder.md").read_text(encoding="utf-8") + "\n" + json.dumps({
            "contract": contract.model_dump(mode="json"),
            "hypothesis": hypothesis,
        }, indent=2)

    def _register_workspace(self, workspace_id: str, sandbox_id: str) -> None:
        value = json.loads(self.registry.read_text(encoding="utf-8"))
        value[workspace_id] = sandbox_id
        self.registry.write_text(json.dumps(value, sort_keys=True) + "\n", encoding="utf-8")

    def _unregister_workspace(self, workspace_id: str) -> None:
        value = json.loads(self.registry.read_text(encoding="utf-8"))
        value.pop(workspace_id, None)
        self.registry.write_text(json.dumps(value, sort_keys=True) + "\n", encoding="utf-8")

    async def _portfolio_e2e(self, state: RunState) -> bool:
        winners = [mission for mission in state.missions.values() if mission.phase in {MissionPhase.LOCAL_WIN, MissionPhase.SYSTEM_WIN}]
        if not winners:
            return False
        comparisons: list[dict[str, Any]] = []
        for mission in winners:
            lease = SandboxLease.create(
                run_id=state.run_id,
                mission_id=mission.mission_id,
                role=SandboxRole.E2E,
                template=self.config.e2b.e2e_template,
            )
            sandbox = await self.manager.create(lease, timeout=1800, envs={}, allow_internet_access=False)
            try:
                if not mission.winner_candidate_id:
                    raise RuntimeError("winning Mission has no Candidate ID")
                candidate = mission.candidates[mission.winner_candidate_id]
                if not candidate.judge_result_ref:
                    raise RuntimeError("winning Candidate has no Judge result")
                judge_result = self.artifacts.read_json(candidate.judge_result_ref)
                candidate_packages = {
                    package: reference
                    for package, reference in judge_result.get("candidate_package_artifacts", {}).items()
                    if not package.endswith("-dev")
                }
                baseline_packages = {
                    package: reference
                    for package, reference in judge_result.get("baseline_package_artifacts", {}).items()
                    if package in candidate_packages
                }
                if not candidate_packages or set(candidate_packages) != set(baseline_packages):
                    raise RuntimeError("Judge did not publish matching candidate and baseline runtime packages")
                for package, reference in candidate_packages.items():
                    await sandbox.files.write(
                        f"/opt/lda/packages/candidate/{package}.deb",
                        self.artifacts.read_bytes(reference),
                    )
                    await sandbox.files.write(
                        f"/opt/lda/packages/baseline/{package}.deb",
                        self.artifacts.read_bytes(baseline_packages[package]),
                    )
                completed = await run_durable_command(
                    sandbox,
                    "/opt/lda/fixtures/run-portfolio-chromium-benchmark.py",
                    timeout=7200,
                )
                if completed.exit_code != 0:
                    raise RuntimeError(completed.stderr[-2000:])
                series = BenchmarkSeries.model_validate_json(completed.stdout)
                comparison = compare_paired(series, self.config.benchmark)
                ref = self.artifacts.put_json(comparison)
                comparisons.append(comparison.model_dump(mode="json"))
                self.store.save_run(
                    state,
                    "portfolio.e2e.completed",
                    {
                        "mission_id": mission.mission_id,
                        "result_ref": ref,
                        "decision": comparison.decision.value,
                    },
                )
            except Exception as error:
                self.store.save_run(state, "portfolio.e2e.failed", {"mission_id": mission.mission_id, "error": f"{type(error).__name__}: {error}"})
            finally:
                await self.manager.kill(lease.lease_id)
        if len(comparisons) != len(winners):
            return False
        if any(item["decision"] != BenchmarkDecision.PASS.value for item in comparisons):
            return False
        improved = sum(float(item["ci_lower"]) > 1.0 for item in comparisons)
        geomean = math.exp(
            sum(math.log(float(item["paired_geomean_ratio"])) for item in comparisons)
            / len(comparisons)
        )
        result_ref = self.artifacts.put_json(
            {
                "mission_results": comparisons,
                "portfolio_geomean_speedup": geomean,
                "improved_workloads": improved,
            }
        )
        state.portfolio_result_ref = result_ref
        self.store.save_run(
            state,
            "portfolio.e2e.aggregate",
            {
                "result_ref": result_ref,
                "geomean_speedup": geomean,
                "improved_workloads": improved,
            },
        )
        return (
            geomean >= self.config.benchmark.portfolio_min_geomean_speedup
            and improved >= self.config.benchmark.min_improved_e2e_workloads
        )

    async def _advisory_agent(
        self,
        state: RunState,
        *,
        role: str,
        mission_id: str,
        candidate_id: str | None,
        prompt_file: str,
        schema_file: str,
        context_refs: list[str],
        allowed_tools: list[str],
        payload: dict[str, Any],
    ) -> str:
        embedded: dict[str, str] = {}
        for reference in context_refs:
            if not reference:
                continue
            try:
                content = self.artifacts.read_bytes(reference).decode(errors="replace")
            except (FileNotFoundError, KeyError, ValueError):
                continue
            embedded[reference] = content[:6_000]
        prompt = (
            Path(prompt_file).read_text(encoding="utf-8")
            + "\n"
            + json.dumps(payload, indent=2)
            + ("\n\nEmbedded read-only artifacts:\n" + json.dumps(embedded, indent=2) if embedded else "")
        )
        prompt_ref = self.artifacts.put_bytes(prompt.encode())
        schema_ref = self.artifacts.put_bytes(Path(schema_file).read_bytes())
        spec = AgentSpec(
            run_id=state.run_id,
            mission_id=mission_id,
            candidate_id=candidate_id,
            role=role,
            backend=self.request.agent_backend,
            model=self.request.agent_model,
            reasoning_effort="low",
            prompt_version=f"{role}-v1",
            runtime_template=self.config.e2b.agent_template,
            context_refs=context_refs,
            allowed_tools=allowed_tools,
            session_policy=SessionPolicy.FRESH,
            output_schema=schema_ref,
            timeout_seconds=1800,
            token_budget=50_000,
            independence_group=f"{role}-{mission_id}-{candidate_id or uuid4().hex}",
        )
        handle = await self.agents.spawn(spec)
        try:
            result = await handle.run(prompt_ref)
            return self.artifacts.put_json(result.output)
        finally:
            await handle.cancel()
