from __future__ import annotations

import hashlib
import json
import re
from dataclasses import asdict, dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any

from .baseline import BaselineSpec


class Lane(str, Enum):
    MAINLINE = "mainline"
    BLOCKING = "blocking"
    QUEUED = "queued"


@dataclass(frozen=True)
class PackagePriority:
    """Pre-work ranking inputs; no package is optimized without a card."""

    package: str
    usage_frequency: float
    performance_criticality: float
    dependency_centrality: float
    architecture_fit: float = 1.0
    rationale: str = ""

    def __post_init__(self) -> None:
        if not self.package or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9+_.:-]*", self.package):
            raise ValueError("package must be a safe package identifier")
        for name in (
            "usage_frequency",
            "performance_criticality",
            "dependency_centrality",
            "architecture_fit",
        ):
            value = getattr(self, name)
            if not 0.0 <= value <= 1.0:
                raise ValueError(f"{name} must be between 0 and 1")

    @property
    def score(self) -> float:
        return (
            0.35 * self.usage_frequency
            + 0.30 * self.performance_criticality
            + 0.25 * self.dependency_centrality
            + 0.10 * self.architecture_fit
        )


@dataclass(frozen=True)
class CompatibilityBoundary:
    """The surgical-replacement contract for one package card."""

    soname_unchanged: bool = True
    exported_symbols_unchanged: bool = True
    abi_types_unchanged: bool = True
    ffi_call_surface_unchanged: bool = True
    behavior_unchanged: bool = True
    configuration_preserved: bool = True
    security_defaults_preserved: bool = True
    result_equivalence_required: bool = True

    def required_checks(self) -> tuple[str, ...]:
        return tuple(
            name
            for name, enabled in asdict(self).items()
            if enabled
        )


@dataclass(frozen=True)
class BenchmarkSpec:
    name: str
    layer: str
    command: tuple[str, ...]
    baseline_command: tuple[str, ...] = ()
    repetitions: int = 3
    timeout_seconds: int = 900
    inputs: tuple[str, ...] = ()
    max_regression_percent: float = 0.0
    min_speedup_percent: float | None = None
    # Hidden-holdout anti-overfitting policy. The Builder only ever sees the
    # train fixtures; at review time the flow generates a second fixture set
    # from a host-held secret seed, points the benchmark at it through
    # holdout_env, and requires holdout_min_speedup_percent on it.
    holdout_min_speedup_percent: float | None = None
    holdout_env: str = ""
    holdout_setup: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if self.layer not in {"micro", "end_to_end"}:
            raise ValueError("benchmark layer must be micro or end_to_end")
        if not self.command or any(not part for part in self.command):
            raise ValueError("benchmark command must be non-empty")
        if self.baseline_command and any(not part for part in self.baseline_command):
            raise ValueError("baseline benchmark command contains an empty argument")
        if self.repetitions < 1 or self.timeout_seconds < 1:
            raise ValueError("benchmark repetitions and timeout must be positive")
        if self.max_regression_percent < 0:
            raise ValueError("max_regression_percent must not be negative")
        if self.min_speedup_percent is not None and self.min_speedup_percent < 0:
            raise ValueError("min_speedup_percent must not be negative")
        if self.holdout_min_speedup_percent is not None:
            if self.holdout_min_speedup_percent < 0:
                raise ValueError("holdout_min_speedup_percent must not be negative")
            if not self.holdout_env or not self.holdout_setup:
                raise ValueError("holdout policy requires holdout_env and holdout_setup")
        if self.holdout_setup and any(not part for part in self.holdout_setup):
            raise ValueError("holdout_setup contains an empty argument")


@dataclass
class TaskCard:
    package: PackagePriority
    goal: str
    source_reference: str
    setup_commands: tuple[tuple[str, ...], ...]
    baseline_tests: tuple[tuple[str, ...], ...]
    dependency_tests: tuple[tuple[str, ...], ...]
    abi_checks: tuple[tuple[str, ...], ...]
    ffi_checks: tuple[tuple[str, ...], ...]
    behavior_checks: tuple[tuple[str, ...], ...]
    package_lifecycle_checks: tuple[tuple[str, ...], ...]
    security_checks: tuple[tuple[str, ...], ...]
    result_equivalence_checks: tuple[tuple[str, ...], ...]
    micro_benchmarks: tuple[BenchmarkSpec, ...]
    end_to_end_benchmarks: tuple[BenchmarkSpec, ...]
    baseline: BaselineSpec = field(default_factory=BaselineSpec)
    compatibility: CompatibilityBoundary = field(default_factory=CompatibilityBoundary)
    lane: Lane = Lane.MAINLINE
    # Paths whose content is digest-pinned after setup; any change to them
    # between rounds invalidates every fence and benchmark verdict. Pinned
    # paths must be byte-reproducible across a fresh-sandbox rebuild (resume
    # re-verifies them), so volatile build outputs like .changes/.buildinfo
    # under baseline/packages are deliberately not pinned.
    integrity_paths: tuple[str, ...] = (
        "/opt/lda/harness",
        "/opt/lda/fixtures",
        "/opt/lda/baseline/root",
        "/opt/lda/baseline/baseline.json",
        "/opt/lda/baseline/manifest",
    )
    # Card-provided pre-benchmark candidate build command (env-wrapped). An
    # empty value falls back to the libpng pilot's builder.
    candidate_build: tuple[str, ...] = ()
    # Card-family known-bad self-probes, run at setup after the generic fence
    # self-check; each must make this card's own checkers flag a bad sample.
    selfcheck_commands: tuple[tuple[str, ...], ...] = ()
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.goal.strip():
            raise ValueError("task card goal must not be empty")
        if not self.source_reference.strip():
            raise ValueError("source reference must be pinned")
        if not self.setup_commands:
            raise ValueError("E2B source setup commands are required")
        if not self.baseline_tests:
            raise ValueError("baseline tests are required")
        if not self.abi_checks or not self.ffi_checks:
            raise ValueError("ABI and FFI checks are required")
        if not all(
            (
                self.behavior_checks,
                self.package_lifecycle_checks,
                self.security_checks,
                self.result_equivalence_checks,
            )
        ):
            raise ValueError("behavior, lifecycle, security, and equivalence checks are required")
        if not self.micro_benchmarks or not self.end_to_end_benchmarks:
            raise ValueError("both benchmark layers are required")
        if any(spec.layer != "micro" for spec in self.micro_benchmarks):
            raise ValueError("micro_benchmarks contains a non-micro spec")
        if any(spec.layer != "end_to_end" for spec in self.end_to_end_benchmarks):
            raise ValueError("end_to_end_benchmarks contains a non-E2E spec")

    def canonical(self) -> dict[str, Any]:
        data = asdict(self)
        data["lane"] = self.lane.value
        data["package"] = asdict(self.package)
        data["micro_benchmarks"] = [asdict(x) for x in self.micro_benchmarks]
        data["end_to_end_benchmarks"] = [asdict(x) for x in self.end_to_end_benchmarks]
        data["baseline"] = self.baseline.canonical()
        return data

    def digest(self) -> str:
        encoded = json.dumps(self.canonical(), sort_keys=True, separators=(",", ":")).encode()
        return hashlib.sha256(encoded).hexdigest()

    def write(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(self.canonical(), indent=2, sort_keys=True) + "\n", encoding="utf-8")


def rank_packages(candidates: list[PackagePriority], limit: int) -> list[PackagePriority]:
    if limit < 1:
        raise ValueError("limit must be positive")
    return sorted(candidates, key=lambda item: (-item.score, item.package))[:limit]
