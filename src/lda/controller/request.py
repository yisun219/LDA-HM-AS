from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field, model_validator

from lda.judge import CommandCheck, JudgeManifest
from lda.models import ResearchSnapshot
from lda.packages import InventoryMetrics


class HypothesisSeed(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    candidate_id: str
    target: str
    mechanism: str
    expected_effect: str
    risks: list[str]
    validation: list[str]


class MissionDefinition(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    package: str
    source_package: str
    source_version: str
    binary_packages: list[str]
    runtime_packages: list[str]
    public_header: str
    probe_body: str
    link_libraries: str
    pkg_config_modules: list[str] = Field(default_factory=list)
    layout_body: str
    ffi_check_command: str
    ffi_library_pattern: str = ""
    ffi_symbol: str = ""
    target_functions: list[str]
    target_workloads: list[str]
    seed_hypotheses: list[HypothesisSeed] = Field(default_factory=list)
    allowed_source_paths: list[str]
    forbidden_paths: list[str]
    baseline_commands: list[list[str]] = Field(default_factory=list)
    extra_baseline_commands: list[list[str]] = Field(default_factory=list)
    profile_commands: list[list[str]] = Field(default_factory=list)
    local_verify_commands: list[list[str]] = Field(default_factory=list)
    abi_manifest: str
    api_manifest: str
    ffi_manifest: str
    microbench_manifest: str
    e2e_manifest: str
    e2e_benchmark_command: list[str] | None = None
    self_tests: list[str]
    reverse_dependency_tests: list[str]
    candidate_budget: int = Field(default=8, gt=0)
    acceptance_policy: str
    judge_manifest: JudgeManifest | None = None

    @model_validator(mode="after")
    def build_execution_manifests(self) -> "MissionDefinition":
        runtime = ",".join(self.runtime_packages)
        downloaded = [f"{package}={self.source_version}" for package in self.binary_packages]
        prepare = [
            "/opt/lda/harness/checks/prepare-mission-baseline.sh",
            self.source_package,
            self.source_version,
            *downloaded,
        ]
        build_baseline = ["/opt/lda/harness/checks/build-generic-package.sh", "baseline", runtime]
        probe = [
            "/opt/lda/harness/checks/prepare-generic-probe.sh",
            self.public_header,
            self.probe_body,
            self.link_libraries,
            ",".join(self.pkg_config_modules),
        ]
        if not self.baseline_commands:
            object.__setattr__(self, "baseline_commands", [prepare, build_baseline, probe, *self.extra_baseline_commands])
        if not self.profile_commands:
            profile_command = "LD_LIBRARY_PATH=$(dirname $(head -1 /opt/lda/baseline/libraries.list)) /opt/lda/fixtures/generic/probe 100000"
            object.__setattr__(self, "profile_commands", [["env", f"LDA_PROFILE_COMMAND={profile_command}", "/opt/lda/harness/checks/profile-package.sh"]])
        if not self.local_verify_commands:
            object.__setattr__(self, "local_verify_commands", [["/opt/lda/harness/checks/run-generic-local-verify.sh", runtime]])
        if self.judge_manifest is None:
            apply = [
                "sudo", "-u", "judge-builder", "--", "sh", "-lc",
                "git -C /opt/lda/work apply /opt/lda/input/candidate.patch && git -C /opt/lda/work add -A && git -C /opt/lda/work -c user.name=LDA -c user.email=lda@localhost commit -m candidate",
            ]
            build_candidate = [
                "sudo", "-u", "judge-builder", "--",
                "/opt/lda/harness/checks/build-generic-package.sh", "candidate", runtime,
            ]
            compatibility: list[CommandCheck] = []
            for name in (
                "soname", "exported-symbols", "symbol-versions", "abidiff", "abi-compliance",
                "header-compile", "struct-layout", "calling-convention", "pkg-config", "cmake-config",
                "install-paths", "ldconfig", "precompiled-binary", "python-ctypes", "python-cffi", "rust-ffi",
                "dlopen-dlsym", "c-cpp-source", "debian-relationships",
            ):
                command = [
                    "env",
                    f"LDA_PUBLIC_HEADER={self.public_header}",
                    f"LDA_LAYOUT_BODY={self.layout_body}",
                    f"LDA_FFI_CHECK_COMMAND={self.ffi_check_command}",
                    f"LDA_FFI_LIBRARY_PATTERN={self.ffi_library_pattern}",
                    f"LDA_FFI_SYMBOL={self.ffi_symbol}",
                    f"LDA_PKG_CONFIG_MODULES={','.join(self.pkg_config_modules)}",
                    f"LDA_LINK_LIBRARIES={self.link_libraries}",
                    "/opt/lda/harness/checks/run-generic-compatibility-check.sh",
                    name,
                ]
                compatibility.append(CommandCheck(name=name, command=command))
            benchmark = [
                "/opt/lda/harness/checks/run-paired-probe-benchmark.py",
                "--layer", "micro", "--name", f"{self.package}-probe", "--loops", "100000",
            ]
            e2e = self.e2e_benchmark_command or [
                "/opt/lda/harness/checks/run-paired-probe-benchmark.py",
                "--layer", "e2e", "--name", f"{self.package}-guardrail", "--loops", "250000",
            ]
            object.__setattr__(self, "judge_manifest", JudgeManifest(
                prepare_baseline=[
                    CommandCheck(name="prepare-official-source", command=prepare),
                    CommandCheck(name="build-official-baseline", command=build_baseline),
                    CommandCheck(name="prepare-precompiled-probe", command=probe),
                    *[CommandCheck(name=f"prepare-extra-{index + 1}", command=command) for index, command in enumerate(self.extra_baseline_commands)],
                    CommandCheck(
                        name="prepare-unprivileged-candidate-user",
                        command=["/opt/lda/harness/checks/prepare-judge-candidate-user.sh"],
                    ),
                ],
                apply_candidate=[CommandCheck(name="apply-candidate-patch", command=apply)],
                build_debs=[CommandCheck(name="build-candidate-debs", command=build_candidate)],
                upstream_self_tests=[CommandCheck(name="upstream-tests", command=["test", "-f", "/opt/lda/candidate/upstream-tests-passed"])],
                compatibility_checks=compatibility,
                precompiled_binary_tests=[CommandCheck(name="original-binary-new-library", command=["/opt/lda/harness/checks/run-generic-compatibility-check.sh", "precompiled-binary"])],
                reverse_dependency_tests=[
                    CommandCheck(
                        name="install-candidate-packages",
                        command=["/opt/lda/harness/checks/run-candidate-package-check.sh", "install"],
                    ),
                    *[
                        CommandCheck(
                            name=f"reverse-build-test-{package}",
                            command=[
                                "/opt/lda/harness/checks/run-candidate-package-check.sh",
                                "reverse-build-test",
                                package,
                            ],
                            timeout_seconds=7200,
                        )
                        for package in self.reverse_dependency_tests
                    ],
                ],
                application_smokes=[CommandCheck(
                    name="installed-candidate-application-smoke",
                    command=["/opt/lda/harness/checks/run-candidate-package-check.sh", "application-smoke"],
                )],
                micro_benchmarks=[CommandCheck(name="micro", command=benchmark)],
                e2e_guardrails=[CommandCheck(name="e2e", command=e2e)],
            ))
        return self


class RunRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    flow: str = "pure-humanize"
    run_id: str
    research_snapshot: ResearchSnapshot
    inventory: list[InventoryMetrics]
    mission_definitions: dict[str, MissionDefinition]
    queue_limit: int = Field(default=10, ge=1, le=10)
    agent_backend: str = "codex-cli"
    agent_model: str = "gpt-5.6-sol"
    reasoning_effort: str = "high"

    def definition(self, package: str) -> MissionDefinition:
        try:
            return self.mission_definitions[package]
        except KeyError as error:
            raise ValueError(f"mission queue package has no definition: {package}") from error
