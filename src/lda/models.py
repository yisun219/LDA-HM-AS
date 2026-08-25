from __future__ import annotations

import hashlib
import json
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:16]}"


def stable_hash(value: Any) -> str:
    payload = json.dumps(value, sort_keys=True, separators=(",", ":"), default=str).encode()
    return hashlib.sha256(payload).hexdigest()


@dataclass(frozen=True)
class AgentSpec:
    run_id: str
    life_cycle_id: str | None
    mission_id: str | None
    candidate_id: str | None
    capability_id: str | None
    role: str
    backend: str
    model: str
    reasoning_effort: str
    prompt_version: str
    context_refs: list[str]
    allowed_tools: list[str]
    runtime_template: str
    workspace_id: str | None
    session_policy: str
    output_schema: str
    timeout_seconds: int
    token_budget: int
    independence_group: str


ALLOWED_ACTIONS = (
    "CREATE_MISSION", "REPRIORITIZE_MISSION", "PAUSE_MISSION", "RESUME_MISSION",
    "STOP_MISSION", "CONTINUE_CANDIDATE", "CREATE_RESEARCH_SNAPSHOT",
    "PROPOSE_CAPABILITY", "START_CAPABILITY_MISSION", "RUN_PORTFOLIO_E2E", "PROPOSE_STOP",
)


@dataclass
class ManagerAction:
    action: str
    target_id: str | None = None
    evidence_refs: list[str] = field(default_factory=list)
    expected_value: float = 0.0
    estimated_cost: float = 0.0
    risk: float = 0.0
    reason_summary: str = ""
    requested_budget: dict[str, float] = field(default_factory=dict)
    preconditions: list[str] = field(default_factory=list)

    def validate_shape(self) -> None:
        if self.action not in ALLOWED_ACTIONS:
            raise ValueError(f"unsupported manager action: {self.action}")
        for name in ("expected_value", "estimated_cost", "risk"):
            value = getattr(self, name)
            if not isinstance(value, (int, float)) or value < 0:
                raise ValueError(f"{name} must be a non-negative number")
        if self.risk > 1:
            raise ValueError("risk must be <= 1")


@dataclass
class RunBudget:
    max_active_missions: int = 2
    builders_per_mission: int = 3
    max_live_codex_sessions: int = 10
    max_live_sandboxes: int = 24
    max_candidates_per_mission: int = 3
    max_attempts_per_candidate: int = 8
    max_life_cycles: int = 20
    remaining_cost: float = 100.0
    spent_cost: float = 0.0


@dataclass
class HardwareProfile:
    cpu_model: str = "Intel Xeon Gold 6548Y+"
    cpuid: str = "unknown"
    microcode: str = "unknown"
    kernel: str = "unknown"
    governor: str = "unknown"
    turbo: str = "unknown"
    numa: str = "unknown"
    smt: str = "unknown"
    affinity: str = "unknown"
    neighbor_load: float = 0.0


@dataclass
class Mission:
    mission_id: str
    package: str
    priority: float
    status: str = "QUEUED"
    expected_value: float = 0.0
    failure_probability: float = 0.0
    attempts: int = 0
    max_attempts: int = 8
    mission_contract_ref: str | None = None
    last_outcome: str | None = None
    capability_id: str | None = None


@dataclass
class Candidate:
    candidate_id: str
    mission_id: str
    status: str = "CREATED"
    micro_speedup: float = 1.0
    micro_ci_lower: float = 1.0
    e2e_speedup: float = 1.0
    fence_passed: bool = False
    judge_status: str = "PENDING"


@dataclass
class Capability:
    capability_id: str
    kind: str
    version: str
    content_hash: str
    scope: list[str]
    status: str = "PROPOSED"
    tests_passed: bool = False
    judge_passed: bool = False


@dataclass
class WorldState:
    run_id: str
    life_cycle: int = 0
    budget: RunBudget = field(default_factory=RunBudget)
    hardware: HardwareProfile = field(default_factory=HardwareProfile)
    research_snapshots: list[dict[str, Any]] = field(default_factory=list)
    package_inventory: list[dict[str, Any]] = field(default_factory=list)
    missions: list[Mission] = field(default_factory=list)
    candidates: list[Candidate] = field(default_factory=list)
    benchmark_ledger: list[dict[str, Any]] = field(default_factory=list)
    outcome_ledger: list[dict[str, Any]] = field(default_factory=list)
    capabilities: list[Capability] = field(default_factory=list)
    fence_versions: dict[str, str] = field(default_factory=lambda: {"abi": "1", "ffi": "1", "api": "1"})
    portfolio_e2e: list[dict[str, Any]] = field(default_factory=list)
    convergence_signals: dict[str, Any] = field(default_factory=dict)
    campaign_input: dict[str, Any] = field(default_factory=dict)
    qualification: dict[str, Any] = field(default_factory=dict)
    active: bool = True

    def dump(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def load(cls, raw: dict[str, Any]) -> "WorldState":
        raw = dict(raw)
        raw["budget"] = RunBudget(**raw.get("budget", {}))
        raw["hardware"] = HardwareProfile(**raw.get("hardware", {}))
        raw["missions"] = [Mission(**x) for x in raw.get("missions", [])]
        raw["candidates"] = [Candidate(**x) for x in raw.get("candidates", [])]
        raw["capabilities"] = [Capability(**x) for x in raw.get("capabilities", [])]
        return cls(**raw)
