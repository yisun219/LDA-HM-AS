from __future__ import annotations

import json
import shlex
from hashlib import sha256
from pathlib import Path
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from lda.artifacts import ArtifactStore
from lda.benchmarks import BenchmarkDecision, BenchmarkSeries, compare_paired
from lda.config import BenchmarkConfig
from lda.e2b import E2BSandboxManager, SandboxLease, SandboxRole, run_durable_command
from lda.models import MissionContract
from lda.security import SecretRedactor


class JudgeDecision(StrEnum):
    LOCAL_WIN = "LOCAL_WIN"
    SYSTEM_WIN = "SYSTEM_WIN"
    REJECTED = "REJECTED"
    INVALID = "INVALID"


class CommandCheck(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    name: str
    command: list[str] = Field(min_length=1)
    timeout_seconds: int = Field(default=3600, gt=0)


class JudgeManifest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    prepare_baseline: list[CommandCheck]
    apply_candidate: list[CommandCheck]
    build_debs: list[CommandCheck]
    upstream_self_tests: list[CommandCheck]
    compatibility_checks: list[CommandCheck] = Field(min_length=18)
    precompiled_binary_tests: list[CommandCheck]
    reverse_dependency_tests: list[CommandCheck]
    application_smokes: list[CommandCheck]
    micro_benchmarks: list[CommandCheck]
    e2e_guardrails: list[CommandCheck]


class CheckResult(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    level: str
    name: str
    command: list[str]
    exit_code: int
    stdout_ref: str
    stderr_ref: str

    @property
    def passed(self) -> bool:
        return self.exit_code == 0


class JudgeResult(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    run_id: str
    mission_id: str
    candidate_id: str
    decision: JudgeDecision
    checks: list[CheckResult]
    benchmark_refs: list[str]
    candidate_package_artifacts: dict[str, str] = Field(default_factory=dict)
    baseline_package_artifacts: dict[str, str] = Field(default_factory=dict)
    reason: str


class DeterministicJudge:
    LEVELS = (
        ("prepare", "prepare_baseline"),
        ("candidate", "apply_candidate"),
        ("build", "build_debs"),
        ("level0-self-test", "upstream_self_tests"),
        ("level1-abi-api-ffi", "compatibility_checks"),
        ("level2-original-binary", "precompiled_binary_tests"),
        ("level3-reverse-dependency", "reverse_dependency_tests"),
        ("level4-application", "application_smokes"),
        ("micro", "micro_benchmarks"),
        ("level5-e2e", "e2e_guardrails"),
    )

    def __init__(self, manager: E2BSandboxManager, artifacts: ArtifactStore, benchmark: BenchmarkConfig) -> None:
        self.manager = manager
        self.artifacts = artifacts
        self.benchmark = benchmark
        self.redactor = SecretRedactor()

    async def evaluate(
        self,
        contract: MissionContract,
        manifest: JudgeManifest,
        *,
        run_id: str,
        candidate_id: str,
        candidate_patch_ref: str,
        template: str,
    ) -> JudgeResult:
        lease = SandboxLease.create(
            run_id=run_id,
            mission_id=contract.mission_id,
            candidate_id=candidate_id,
            role=SandboxRole.JUDGE,
            template=template,
        )
        sandbox = await self.manager.create(
            lease,
            envs={},
            # The deterministic Judge must independently fetch the immutable
            # Ubuntu Snapshot named by its manifest. It receives no model or
            # E2B credentials, and every download command/hash is recorded.
            allow_internet_access=True,
            timeout=7200,
        )
        await sandbox.files.write("/opt/lda/input/contract.json", contract.model_dump_json(indent=2))
        await sandbox.files.write("/opt/lda/input/candidate.patch", self.artifacts.read_bytes(candidate_patch_ref))
        checks: list[CheckResult] = []
        benchmark_refs: list[str] = []
        try:
            for level, attribute in self.LEVELS:
                for check in getattr(manifest, attribute):
                    result = await run_durable_command(
                        sandbox,
                        " ".join(shlex.quote(part) for part in check.command),
                        timeout=check.timeout_seconds,
                        envs={},
                    )
                    self.redactor.assert_clean(str(result.stdout))
                    self.redactor.assert_clean(str(result.stderr))
                    stdout_ref = self.artifacts.put_bytes(str(result.stdout).encode())
                    stderr_ref = self.artifacts.put_bytes(str(result.stderr).encode())
                    recorded = CheckResult(
                        level=level,
                        name=check.name,
                        command=check.command,
                        exit_code=int(result.exit_code),
                        stdout_ref=stdout_ref,
                        stderr_ref=stderr_ref,
                    )
                    checks.append(recorded)
                    if not recorded.passed:
                        decision = JudgeDecision.INVALID if level in {"prepare", "build"} else JudgeDecision.REJECTED
                        return JudgeResult(
                            run_id=run_id,
                            mission_id=contract.mission_id,
                            candidate_id=candidate_id,
                            decision=decision,
                            checks=checks,
                            benchmark_refs=benchmark_refs,
                            reason=f"{level} failed: {check.name}",
                        )
                    if level == "prepare" and check is manifest.prepare_baseline[-1]:
                        identity = await self._verify_baseline_identity(sandbox, contract)
                        checks.append(identity)
                        if not identity.passed:
                            return JudgeResult(
                                run_id=run_id,
                                mission_id=contract.mission_id,
                                candidate_id=candidate_id,
                                decision=JudgeDecision.INVALID,
                                checks=checks,
                                benchmark_refs=benchmark_refs,
                                reason="prepare failed: frozen-baseline-identity",
                            )
                    if level in {"micro", "level5-e2e"}:
                        series = BenchmarkSeries.model_validate(json.loads(result.stdout))
                        comparison = compare_paired(series, self.benchmark)
                        reference = self.artifacts.put_json(comparison)
                        benchmark_refs.append(reference)
                        if comparison.decision is BenchmarkDecision.INVALID:
                            return JudgeResult(
                                run_id=run_id,
                                mission_id=contract.mission_id,
                                candidate_id=candidate_id,
                                decision=JudgeDecision.INVALID,
                                checks=checks,
                                benchmark_refs=benchmark_refs,
                                reason=comparison.reason,
                            )
                        if comparison.decision is BenchmarkDecision.FAIL:
                            return JudgeResult(
                                run_id=run_id,
                                mission_id=contract.mission_id,
                                candidate_id=candidate_id,
                                decision=JudgeDecision.REJECTED,
                                checks=checks,
                                benchmark_refs=benchmark_refs,
                                reason=comparison.reason,
                            )
            e2e = [
                self.artifacts.read_json(reference)
                for reference in benchmark_refs
                if self.artifacts.read_json(reference).get("layer") == "e2e"
            ]
            system_win = any(float(item["ci_lower"]) > 1.0 for item in e2e)
            candidate_packages = await self._publish_debs(
                sandbox, "/opt/lda/candidate/packages"
            )
            baseline_packages = await self._publish_debs(
                sandbox, "/opt/lda/baseline"
            )
            candidate_packages = {
                package: reference
                for package, reference in candidate_packages.items()
                if package in baseline_packages
            }
            return JudgeResult(
                run_id=run_id,
                mission_id=contract.mission_id,
                candidate_id=candidate_id,
                decision=JudgeDecision.SYSTEM_WIN if system_win else JudgeDecision.LOCAL_WIN,
                checks=checks,
                benchmark_refs=benchmark_refs,
                candidate_package_artifacts=candidate_packages,
                baseline_package_artifacts=baseline_packages,
                reason="all deterministic fences passed",
            )
        finally:
            await self.manager.kill(lease.lease_id)

    async def _publish_debs(self, sandbox: Any, directory: str) -> dict[str, str]:
        listing = await sandbox.commands.run(
            f"find {shlex.quote(directory)} -maxdepth 1 -type f -name '*.deb' -print"
        )
        published: dict[str, str] = {}
        for path in sorted(line.strip() for line in listing.stdout.splitlines() if line.strip()):
            identity = await sandbox.commands.run(f"dpkg-deb -f {shlex.quote(path)} Package")
            if identity.exit_code != 0:
                continue
            package = identity.stdout.strip()
            if not package:
                continue
            raw = await sandbox.files.read(path)
            content = raw if isinstance(raw, bytes) else str(raw).encode()
            published[package] = self.artifacts.put_bytes(content)
        return published

    async def _verify_baseline_identity(
        self, sandbox: Any, contract: MissionContract
    ) -> CheckResult:
        command = ["internal", "verify-frozen-baseline-identity"]
        errors: list[str] = []
        source = await sandbox.files.read("/opt/lda/baseline/source.tar.bundle")
        source_bytes = source if isinstance(source, bytes) else str(source).encode()
        actual_source_hash = sha256(source_bytes).hexdigest()
        if actual_source_hash != contract.official_source_hash:
            errors.append(
                f"source hash mismatch: expected {contract.official_source_hash}, got {actual_source_hash}"
            )

        listing = await sandbox.commands.run(
            "find /opt/lda/baseline -maxdepth 1 -type f -name '*.deb' -print"
        )
        actual_debs: dict[str, str] = {}
        for path in sorted(line.strip() for line in listing.stdout.splitlines() if line.strip()):
            raw = await sandbox.files.read(path)
            content = raw if isinstance(raw, bytes) else str(raw).encode()
            actual_debs[Path(path).name] = sha256(content).hexdigest()
        if actual_debs != contract.official_deb_hashes:
            errors.append(
                "official Debian package hashes differ from the immutable Mission Contract"
            )

        stdout_ref = self.artifacts.put_bytes(
            json.dumps(
                {
                    "source_sha256": actual_source_hash,
                    "deb_sha256": actual_debs,
                },
                sort_keys=True,
            ).encode()
        )
        stderr_ref = self.artifacts.put_bytes("\n".join(errors).encode())
        return CheckResult(
            level="prepare",
            name="frozen-baseline-identity",
            command=command,
            exit_code=1 if errors else 0,
            stdout_ref=stdout_ref,
            stderr_ref=stderr_ref,
        )
