from __future__ import annotations

from dataclasses import asdict, dataclass, field
from enum import Enum
from typing import Any


class Phase(str, Enum):
    SETUP = "setup"
    IDEA = "idea"
    PLAN = "plan"
    IMPLEMENTATION = "implementation"
    REGULAR_REVIEW = "regular_review"
    FULL_ALIGNMENT = "full_alignment"
    DRIFT_RECOVERY = "drift_recovery"
    CODE_REVIEW = "code_review"
    FINALIZE = "finalize"
    METHODOLOGY_ANALYSIS = "methodology_analysis"
    COMPLETE = "complete"
    MAX_ITER = "max_iter"
    STOP = "stop"
    UNEXPECTED = "unexpected"


class MainlineVerdict(str, Enum):
    ADVANCED = "ADVANCED"
    STALLED = "STALLED"
    REGRESSED = "REGRESSED"


class TerminalReason(str, Enum):
    COMPLETE = "complete"
    MAX_ITER = "max_iter"
    STOP = "stop"
    UNEXPECTED = "unexpected"


@dataclass(frozen=True)
class FlowConfig:
    max_iterations: int = 42
    full_alignment_interval: int = 5
    drift_recovery_threshold: int = 2
    circuit_breaker_threshold: int = 3
    require_clean_worktree: bool = True
    require_pushed_rounds: bool = False
    large_file_line_limit: int = 2000
    # Live supervision: a Builder turn whose trace stops growing for this many
    # minutes is killed and judged as a failed round.
    builder_stall_minutes: int = 15

    def __post_init__(self) -> None:
        if self.max_iterations < 1:
            raise ValueError("max_iterations must be positive")
        if self.full_alignment_interval < 1:
            raise ValueError("full_alignment_interval must be positive")
        if self.drift_recovery_threshold < 1:
            raise ValueError("drift_recovery_threshold must be positive")
        if self.circuit_breaker_threshold <= self.drift_recovery_threshold:
            raise ValueError("circuit breaker must follow drift recovery")
        if self.builder_stall_minutes < 1:
            raise ValueError("builder_stall_minutes must be positive")


@dataclass(frozen=True)
class ReviewResult:
    verdict: MainlineVerdict
    complete: bool = False
    feedback: str = ""
    blocking_findings: tuple[str, ...] = ()


@dataclass
class FlowState:
    schema_version: int = 1
    run_id: str = ""
    phase: Phase = Phase.SETUP
    current_round: int = 0
    plan_hash: str = ""
    plan_file: str = "plan.md"
    start_branch: str = ""
    base_branch: str = ""
    base_commit: str = ""
    stall_count: int = 0
    last_verdict: MainlineVerdict | None = None
    drift_recovery_required: bool = False
    review_started: bool = False
    terminal_reason: TerminalReason | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["phase"] = self.phase.value
        data["last_verdict"] = self.last_verdict.value if self.last_verdict else None
        data["terminal_reason"] = (
            self.terminal_reason.value if self.terminal_reason else None
        )
        return data

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> FlowState:
        expected = {field.name for field in cls.__dataclass_fields__.values()}
        if set(data) != expected:
            missing = expected - set(data)
            extra = set(data) - expected
            raise ValueError(f"invalid state fields: missing={missing}, extra={extra}")
        parsed = dict(data)
        parsed["phase"] = Phase(parsed["phase"])
        if parsed["last_verdict"] is not None:
            parsed["last_verdict"] = MainlineVerdict(parsed["last_verdict"])
        if parsed["terminal_reason"] is not None:
            parsed["terminal_reason"] = TerminalReason(parsed["terminal_reason"])
        return cls(**parsed)
