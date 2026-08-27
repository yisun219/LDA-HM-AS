"""LDA-HM flow primitives."""

from .artifacts import ArtifactStore
from .baseline import BaselineSpec
from .benchmark import (
    BenchSample,
    BenchmarkEnvironmentError,
    BenchmarkObservation,
    BenchmarkReport,
    BenchmarkRunner,
    PairedComparison,
    compare_paired,
    parse_bench_samples,
)
from .agent_command import CommandAgent, CommandSession
from .fence import FenceResult, FenceSuite, integrity_manifest_command
from .flow import HumanizeFlow, InvalidTransition
from .gates import GateContext, GateResult, GateRunner
from .execution import (
    LDAExecution,
    holdout_setup_command,
    judge_comparison,
    paired_with_retry,
    scan_candidate_patch_text,
)
from .supervision import (
    BuilderWatchdog,
    RunPulse,
    Supervisor,
    SupervisorDecision,
    TraceStats,
    parse_supervisor_answer,
)
from .priority import select_package_batch
from .sandbox import E2BSandbox, FakeSandbox, SandboxResult, SandboxUnavailable
from .stages import FenceBlocked, GateBlocked, HumanizeStages
from .task_card import (
    BenchmarkSpec,
    CompatibilityBoundary,
    Lane,
    PackagePriority,
    TaskCard,
)
from .types import (
    FlowConfig,
    FlowState,
    MainlineVerdict,
    Phase,
    ReviewResult,
    TerminalReason,
)

__all__ = [
    "ArtifactStore",
    "BaselineSpec",
    "BenchSample",
    "BenchmarkEnvironmentError",
    "BuilderWatchdog",
    "RunPulse",
    "Supervisor",
    "SupervisorDecision",
    "TraceStats",
    "parse_supervisor_answer",
    "paired_with_retry",
    "integrity_manifest_command",
    "BenchmarkObservation",
    "BenchmarkReport",
    "BenchmarkRunner",
    "PairedComparison",
    "compare_paired",
    "parse_bench_samples",
    "holdout_setup_command",
    "judge_comparison",
    "scan_candidate_patch_text",
    "BenchmarkSpec",
    "CommandAgent",
    "CommandSession",
    "CompatibilityBoundary",
    "E2BSandbox",
    "FakeSandbox",
    "FenceResult",
    "FenceSuite",
    "FenceBlocked",
    "GateBlocked",
    "FlowConfig",
    "FlowState",
    "GateContext",
    "GateResult",
    "GateRunner",
    "HumanizeFlow",
    "HumanizeStages",
    "LDAExecution",
    "InvalidTransition",
    "Lane",
    "MainlineVerdict",
    "PackagePriority",
    "Phase",
    "ReviewResult",
    "SandboxResult",
    "SandboxUnavailable",
    "select_package_batch",
    "TaskCard",
    "TerminalReason",
]
