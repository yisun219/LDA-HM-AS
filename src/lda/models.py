from __future__ import annotations

from datetime import datetime, timezone
from enum import StrEnum
from hashlib import sha256
from typing import Any, Literal
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def stable_digest(value: BaseModel | dict[str, Any]) -> str:
    if isinstance(value, BaseModel):
        raw = value.model_dump_json(exclude_none=False)
    else:
        import json

        raw = json.dumps(value, sort_keys=True, separators=(",", ":"))
    return sha256(raw.encode()).hexdigest()


class FrozenModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class RunPhase(StrEnum):
    RUN_CREATED = "RUN_CREATED"
    E2B_PREFLIGHT = "E2B_PREFLIGHT"
    RESEARCH_FROZEN = "RESEARCH_FROZEN"
    PORTFOLIO_PLANNED = "PORTFOLIO_PLANNED"
    MISSION_QUEUE_FROZEN = "MISSION_QUEUE_FROZEN"
    MISSION_BASELINE = "MISSION_BASELINE"
    PROFILE = "PROFILE"
    HYPOTHESIS = "HYPOTHESIS"
    CANDIDATE_FORK = "CANDIDATE_FORK"
    BUILD = "BUILD"
    LOCAL_VERIFY = "LOCAL_VERIFY"
    ADVERSARIAL_REVIEW = "ADVERSARIAL_REVIEW"
    CLEAN_JUDGE = "CLEAN_JUDGE"
    NEXT_MISSION = "NEXT_MISSION"
    PORTFOLIO_E2E = "PORTFOLIO_E2E"
    RELEASE_READY = "RELEASE_READY"
    COMPLETED_WITHOUT_RELEASE = "COMPLETED_WITHOUT_RELEASE"
    CANCELLED = "CANCELLED"
    FAILED = "FAILED"


class MissionPhase(StrEnum):
    QUEUED = "QUEUED"
    BASELINE = "BASELINE"
    PROFILE = "PROFILE"
    HYPOTHESIS = "HYPOTHESIS"
    CANDIDATES = "CANDIDATES"
    JUDGING = "JUDGING"
    LOCAL_WIN = "LOCAL_WIN"
    SYSTEM_WIN = "SYSTEM_WIN"
    REJECTED = "REJECTED"
    INVALID = "INVALID"
    NOT_HOT = "NOT_HOT"


class CandidateStatus(StrEnum):
    CREATED = "CREATED"
    BUILDING = "BUILDING"
    LOCAL_VERIFY = "LOCAL_VERIFY"
    REVIEWED = "REVIEWED"
    JUDGING = "JUDGING"
    LOCAL_WIN = "LOCAL_WIN"
    SYSTEM_WIN = "SYSTEM_WIN"
    REJECTED = "REJECTED"
    INVALID = "INVALID"
    CANCELLED = "CANCELLED"


class SessionPolicy(StrEnum):
    FRESH = "fresh"
    PERSISTENT = "persistent"


class AgentSpec(FrozenModel):
    run_id: str
    mission_id: str
    candidate_id: str | None = None
    role: str
    backend: Literal["codex-sdk", "codex-cli", "fake"] = "codex-sdk"
    model: str
    reasoning_effort: str
    prompt_version: str
    context_refs: list[str] = Field(default_factory=list)
    allowed_tools: list[str] = Field(default_factory=list)
    runtime_template: str = "lda-agent-runtime"
    workspace_id: str | None = None
    session_policy: SessionPolicy
    output_schema: str
    timeout_seconds: int = Field(gt=0)
    token_budget: int = Field(gt=0)
    independence_group: str


class AgentResult(FrozenModel):
    agent_id: str
    thread_id: str
    output: dict[str, Any]
    trace_ref: str
    checkpoint_ref: str | None = None
    usage_tokens: int = 0
    completed_at: datetime = Field(default_factory=utc_now)


class ResearchHint(FrozenModel):
    package: str
    target_path: str = ""
    performance_hypothesis: str
    optimization_approach: str = ""
    workloads: list[str] = Field(default_factory=list)
    cpu_features: list[str] = Field(default_factory=list)
    risks: list[str] = Field(default_factory=list)
    evidence_sources: list[str] = Field(default_factory=list)
    confidence: float = Field(ge=0, le=1)
    source_hash: str = Field(pattern=r"^[0-9a-f]{64}$")


class ResearchSourceArtifact(FrozenModel):
    file_name: str
    original_path: str
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    artifact_ref: str = Field(pattern=r"^[0-9a-f]{64}$")
    size_bytes: int = Field(ge=0)

    @model_validator(mode="after")
    def artifact_matches_source(self) -> "ResearchSourceArtifact":
        if self.artifact_ref != self.sha256:
            raise ValueError("research source artifact must preserve the original SHA-256")
        return self


class ResearchSnapshot(FrozenModel):
    snapshot_id: str
    created_at: datetime = Field(default_factory=utc_now)
    source_files: tuple[str, ...]
    source_artifacts: tuple[ResearchSourceArtifact, ...]
    hints: tuple[ResearchHint, ...]
    content_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    frozen: Literal[True] = True


class PackageScore(FrozenModel):
    package: str
    usage_frequency: float = Field(ge=0, le=1)
    measured_cpu_share: float = Field(ge=0, le=1)
    dependency_centrality: float = Field(ge=0, le=1)
    workload_generality: float = Field(ge=0, le=1)
    expected_effort_efficiency: float = Field(ge=0, le=1)
    compatibility_risk: float = Field(ge=0, le=1)
    priority: float = Field(ge=-1, le=1)

    @model_validator(mode="after")
    def validate_priority(self) -> "PackageScore":
        expected = (
            0.25 * self.usage_frequency
            + 0.25 * self.measured_cpu_share
            + 0.20 * self.dependency_centrality
            + 0.15 * self.workload_generality
            + 0.15 * self.expected_effort_efficiency
            - self.compatibility_risk
        )
        if abs(self.priority - expected) > 1e-9:
            raise ValueError("priority does not match the normalized LDA formula")
        return self


class QualificationRecord(FrozenModel):
    """Immutable evidence record created before a package becomes a Mission."""

    package: str
    source_package: str | None = None
    source_version: str | None = None
    binary_packages: tuple[str, ...] = ()
    architecture: str = "amd64"
    snapshot: str
    binary_identity_verified: bool = False
    dependency_identity_verified: bool = False
    unresolved_edges_verified: bool = False
    clean_rebuild_verified: bool = False
    hotspot_verified: bool = False
    microbench_feasible: bool = False
    e2e_feasible: bool = False
    drop_in_replacement_feasible: bool = False
    status: Literal["PENDING", "QUALIFIED", "REJECTED"] = "PENDING"
    evidence_refs: tuple[str, ...] = ()
    notes: tuple[str, ...] = ()


class MissionQueue(FrozenModel):
    run_id: str
    research_snapshot_id: str
    missions: tuple[str, ...] = Field(min_length=1, max_length=10)
    scores: tuple[PackageScore, ...]
    frozen_at: datetime = Field(default_factory=utc_now)
    queue_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    frozen: Literal[True] = True

    @field_validator("missions")
    @classmethod
    def unique_missions(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if len(value) != len(set(value)):
            raise ValueError("mission queue contains duplicates")
        return value


class MissionContract(FrozenModel):
    mission_id: str
    source_package: str
    binary_packages: list[str]
    ubuntu_version: Literal["26.04"] = "26.04"
    official_source_hash: str
    official_deb_hashes: dict[str, str]
    target_functions: list[str]
    target_workloads: list[str]
    allowed_source_paths: list[str]
    forbidden_paths: list[str]
    abi_manifest: str
    api_manifest: str
    ffi_manifest: str
    self_tests: list[str]
    reverse_dependency_tests: list[str]
    microbench_manifest: str
    e2e_manifest: str
    hardware_profile: str
    candidate_budget: int = Field(gt=0)
    acceptance_policy: str
    contract_hash: str = ""

    @model_validator(mode="after")
    def ensure_sealed(self) -> "MissionContract":
        if not self.contract_hash:
            payload = self.model_dump(exclude={"contract_hash"})
            object.__setattr__(self, "contract_hash", stable_digest(payload))
        return self


class CandidateState(BaseModel):
    model_config = ConfigDict(extra="forbid")
    candidate_id: str
    mission_id: str
    status: CandidateStatus = CandidateStatus.CREATED
    attempts: int = 0
    no_improvement_rounds: int = 0
    builder_thread_id: str | None = None
    workspace_sandbox_id: str | None = None
    best_speedup: float = 1.0
    judge_result_ref: str | None = None


class MissionState(BaseModel):
    model_config = ConfigDict(extra="forbid")
    mission_id: str
    phase: MissionPhase = MissionPhase.QUEUED
    contract_ref: str | None = None
    candidates: dict[str, CandidateState] = Field(default_factory=dict)
    winner_candidate_id: str | None = None


class RunState(BaseModel):
    model_config = ConfigDict(extra="forbid")
    schema_version: Literal[1] = 1
    run_id: str = Field(default_factory=lambda: uuid4().hex)
    phase: RunPhase = RunPhase.RUN_CREATED
    research_snapshot_id: str
    mission_queue_hash: str | None = None
    current_mission_index: int = 0
    missions: dict[str, MissionState] = Field(default_factory=dict)
    controller_sandbox_id: str | None = None
    portfolio_result_ref: str | None = None
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)
    cancelled: bool = False
    failure: str | None = None

    def touch(self) -> None:
        self.updated_at = utc_now()
