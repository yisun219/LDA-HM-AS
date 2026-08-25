from pathlib import Path

import pytest

from lda.artifacts import ArtifactStore
from lda.config import BenchmarkConfig
from lda.judge import CommandCheck, DeterministicJudge, JudgeDecision, JudgeManifest
from lda.models import MissionContract

from .fakes import FakeSandbox


class Manager:
    def __init__(self, fail_token: str) -> None:
        self.sandbox = FakeSandbox("judge", fail_token)

    async def create(self, lease, **kwargs):
        return self.sandbox

    async def kill(self, lease_id):
        await self.sandbox.kill()


def manifest(fail_name: str) -> JudgeManifest:
    compatibility = [CommandCheck(name=f"abi-{index}", command=[f"check-{index}"]) for index in range(18)]
    compatibility[5] = CommandCheck(name="ffi", command=[fail_name])
    return JudgeManifest(
        prepare_baseline=[CommandCheck(name="prepare", command=["prepare"])],
        apply_candidate=[CommandCheck(name="apply", command=["apply"])],
        build_debs=[CommandCheck(name="build", command=["build"])],
        upstream_self_tests=[CommandCheck(name="self", command=["self"])],
        compatibility_checks=compatibility,
        precompiled_binary_tests=[CommandCheck(name="binary", command=["binary"])],
        reverse_dependency_tests=[CommandCheck(name="reverse", command=["reverse"])],
        application_smokes=[CommandCheck(name="app", command=["app"])],
        micro_benchmarks=[CommandCheck(name="micro", command=["run-paired-probe-benchmark.py", "--layer", "micro"])],
        e2e_guardrails=[CommandCheck(name="e2e", command=["run-paired-probe-benchmark.py", "--layer", "e2e"])],
    )


def contract() -> MissionContract:
    return MissionContract(
        mission_id="mission",
        source_package="fixture",
        binary_packages=["fixture"],
        official_source_hash="a" * 64,
        official_deb_hashes={"fixture.deb": "b" * 64},
        target_functions=["fixture"],
        target_workloads=["fixture"],
        allowed_source_paths=["/opt/lda/work/src"],
        forbidden_paths=["/opt/lda/tests"],
        abi_manifest="abi",
        api_manifest="api",
        ffi_manifest="ffi",
        self_tests=["self"],
        reverse_dependency_tests=["reverse"],
        microbench_manifest="micro",
        e2e_manifest="e2e",
        hardware_profile="hardware",
        candidate_budget=8,
        acceptance_policy="strict",
    )


@pytest.mark.parametrize("failure", ["abi-fail", "ffi-fail"])
async def test_abi_and_ffi_failure_reject_candidate(tmp_path: Path, failure: str) -> None:
    artifacts = ArtifactStore(tmp_path / "artifacts")
    patch = artifacts.put_bytes(b"patch")
    judge = DeterministicJudge(Manager(failure), artifacts, BenchmarkConfig())
    result = await judge.evaluate(
        contract(),
        manifest(failure),
        run_id="run",
        candidate_id="candidate",
        candidate_patch_ref=patch,
        template="judge",
    )
    assert result.decision is JudgeDecision.REJECTED
