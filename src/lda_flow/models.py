"""Strict campaign configuration models."""

from __future__ import annotations

from pathlib import PurePosixPath
from typing import Annotated, Literal, Self

import yaml
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

Score = Annotated[float, Field(ge=0, le=100)]


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class Command(StrictModel):
    argv: tuple[str, ...]
    timeout_seconds: int = Field(default=1800, ge=1, le=21600)
    cwd: str = "/workspace/mission"
    env: dict[str, str] = Field(default_factory=dict)

    @field_validator("argv")
    @classmethod
    def argv_is_nonempty(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if not value or any(not item for item in value):
            raise ValueError("command argv must be non-empty")
        return value


class Signal(StrictModel):
    score: Score
    evidence: str = Field(min_length=8)
    source: str = Field(min_length=3)


class PackageSignals(StrictModel):
    usage_frequency: Signal
    performance_criticality: Signal
    dependency_centrality: Signal
    optimization_feasibility: Signal
    verification_readiness: Signal
    estimated_cost: Signal


class PriorityWeights(StrictModel):
    usage_frequency: float = 0.30
    performance_criticality: float = 0.30
    dependency_centrality: float = 0.25
    optimization_feasibility: float = 0.10
    verification_readiness: float = 0.05
    estimated_cost: float = -0.15


class CpuPolicy(StrictModel):
    strategy: Literal["generic_amd64_with_runtime_dispatch"]
    expected_model_substring: str = "Intel(R) Xeon(R) Gold 6548Y+"
    forbidden_global_flags: tuple[str, ...] = ("-march=native", "-march=sapphirerapids")
    require_generic_fallback: Literal[True] = True
    require_dispatch_test: Literal[True] = True


class Benchmark(StrictModel):
    name: str
    layer: Literal["micro", "package_e2e", "campaign_e2e"]
    baseline: Command
    candidate: Command
    warmups: int = Field(default=2, ge=1)
    samples: int = Field(default=7, ge=3)
    lower_is_better: bool = True
    max_relative_mad: float = Field(default=0.08, gt=0, lt=1)
    min_speedup: float = Field(default=1.0, gt=0)
    checksum: str = Field(min_length=8)


class PackageExpectation(StrictModel):
    binary_package: str
    architecture: Literal["amd64"]
    multi_arch: str = "same"
    baseline_version_command: Command
    candidate_version_command: Command
    control_fields: tuple[str, ...] = (
        "Package",
        "Architecture",
        "Multi-Arch",
        "Depends",
        "Pre-Depends",
        "Provides",
        "Conflicts",
        "Replaces",
        "Breaks",
    )
    shared_objects: tuple[str, ...]
    headers: tuple[str, ...]


class HardFences(StrictModel):
    package: Literal[True] = True
    abi: Literal[True] = True
    api_header: Literal[True] = True
    ffi: Literal[True] = True
    self_test: Literal[True] = True
    dependency_test: Literal[True] = True
    protected_paths: Literal[True] = True
    source_allowlist: Literal[True] = True
    trace: Literal[True] = True
    cpu_policy: Literal[True] = True


class MissionCommands(StrictModel):
    source_acquire: tuple[Command, ...]
    baseline_download: tuple[Command, ...]
    baseline_extract: tuple[Command, ...]
    clean_candidate: tuple[Command, ...]
    build_candidate: tuple[Command, ...]
    candidate_extract: tuple[Command, ...]
    package_fence: tuple[Command, ...]
    abi_fence: tuple[Command, ...]
    header_fence: tuple[Command, ...]
    ffi_fence: tuple[Command, ...]
    self_test: tuple[Command, ...]
    dependency_test: tuple[Command, ...]

    @model_validator(mode="after")
    def all_groups_present(self) -> Self:
        for name in type(self).model_fields:
            if not getattr(self, name):
                raise ValueError(f"{name} must contain a real command")
        return self


class Mission(StrictModel):
    id: str = Field(pattern=r"^[a-z0-9][a-z0-9-]+$")
    source_package: str
    package: PackageExpectation
    signals: PackageSignals
    cpu_policy: CpuPolicy
    hard_fences: HardFences = Field(default_factory=HardFences)
    protected_paths: tuple[str, ...]
    allowed_source_paths: tuple[str, ...]
    allowed_untracked_globs: tuple[str, ...] = ()
    commands: MissionCommands
    benchmarks: tuple[Benchmark, ...]
    max_rounds: int = Field(default=12, ge=1, le=100)
    max_stalled_rounds: int = Field(default=3, ge=1, le=10)
    snapshot_id: str | None = None

    @field_validator("protected_paths", "allowed_source_paths")
    @classmethod
    def paths_are_relative(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if not value:
            raise ValueError("path policy cannot be empty")
        for item in value:
            path = PurePosixPath(item)
            if path.is_absolute() or ".." in path.parts:
                raise ValueError(f"unsafe relative path: {item}")
        return value

    @model_validator(mode="after")
    def benchmark_layers_exist(self) -> Self:
        layers = {item.layer for item in self.benchmarks}
        if "micro" not in layers or "package_e2e" not in layers:
            raise ValueError("each mission requires micro and package_e2e benchmarks")
        return self


class AgentSettings(StrictModel):
    builder: str
    reviewer: str
    forward_env: tuple[str, ...]

    @field_validator("forward_env")
    @classmethod
    def credentials_are_allowlisted(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        allowed = {
            "OPENAI_API_KEY",
            "ANTHROPIC_API_KEY",
            "DEEPSEEK_API_KEY",
            "DEEPSEEK_BASE_URL",
        }
        unknown = set(value) - allowed
        if unknown:
            raise ValueError(f"unsupported forwarded environment variables: {sorted(unknown)}")
        return value


class E2BSettings(StrictModel):
    template: str = "lda-base"
    timeout_seconds: int = Field(default=21600, ge=600, le=86400)
    api_url_env: Literal["E2B_API_URL"] = "E2B_API_URL"
    sandbox_url_env: Literal["E2B_SANDBOX_URL"] = "E2B_SANDBOX_URL"
    api_key_env: Literal["E2B_API_KEY"] = "E2B_API_KEY"
    access_token_env: Literal["E2B_ACCESS_TOKEN"] = "E2B_ACCESS_TOKEN"  # noqa: S105


class Campaign(StrictModel):
    schema_version: Literal[1]
    name: str
    ubuntu_release: Literal["26.04"]
    top_k: int = Field(ge=1)
    concurrency: int = Field(default=2, ge=1, le=16)
    weights: PriorityWeights = Field(default_factory=PriorityWeights)
    agents: AgentSettings
    e2b: E2BSettings = Field(default_factory=E2BSettings)
    missions: tuple[Mission, ...]
    campaign_benchmarks: tuple[Benchmark, ...]
    portfolio_min_geomean_speedup: float = Field(default=1.01, gt=0)
    portfolio_max_regression: float = Field(default=0.02, ge=0, lt=1)

    @model_validator(mode="after")
    def campaign_is_runnable(self) -> Self:
        if self.top_k > len(self.missions):
            raise ValueError("top_k cannot exceed mission count")
        if not self.campaign_benchmarks:
            raise ValueError("campaign benchmarks cannot be empty")
        ids = [mission.id for mission in self.missions]
        if len(ids) != len(set(ids)):
            raise ValueError("mission ids must be unique")
        return self

    @classmethod
    def from_yaml(cls, path: str) -> Self:
        with open(path, encoding="utf-8") as handle:
            return cls.model_validate(yaml.safe_load(handle))
