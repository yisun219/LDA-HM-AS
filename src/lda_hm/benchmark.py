from __future__ import annotations

import json
import statistics
import time
from dataclasses import asdict, dataclass
from pathlib import Path

from .sandbox import Sandbox, SandboxResult
from .task_card import BenchmarkSpec


@dataclass(frozen=True)
class BenchmarkObservation:
    layer: str
    name: str
    repetition: int
    exit_code: int
    duration_seconds: float
    stdout: str
    stderr: str
    sandbox_id: str


@dataclass(frozen=True)
class BenchmarkReport:
    layer: str
    name: str
    observations: tuple[BenchmarkObservation, ...]

    @property
    def successful(self) -> bool:
        return bool(self.observations) and all(x.exit_code == 0 for x in self.observations)

    @property
    def median_seconds(self) -> float:
        return statistics.median(x.duration_seconds for x in self.observations)

    def write(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        value = asdict(self) | {"successful": self.successful, "median_seconds": self.median_seconds}
        path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")


class BenchmarkRunner:
    def __init__(self, sandbox: Sandbox) -> None:
        self.sandbox = sandbox

    def run(self, spec: BenchmarkSpec) -> BenchmarkReport:
        return self._run_command(spec, spec.command)

    def run_baseline(self, spec: BenchmarkSpec) -> BenchmarkReport:
        return self._run_command(spec, spec.baseline_command or spec.command)

    def run_paired(self, spec: BenchmarkSpec) -> tuple[BenchmarkReport, BenchmarkReport]:
        baseline_command = spec.baseline_command or spec.command
        baseline: list[BenchmarkObservation] = []
        candidate: list[BenchmarkObservation] = []
        for repetition in range(spec.repetitions):
            ordered = (
                ((baseline_command, baseline), (spec.command, candidate))
                if repetition % 2 == 0
                else ((spec.command, candidate), (baseline_command, baseline))
            )
            for command, target in ordered:
                result = self.sandbox.run(command, timeout_seconds=spec.timeout_seconds)
                target.append(self._observation(spec, repetition, result))
                if not result.ok:
                    return (
                        BenchmarkReport(spec.layer, spec.name + "-baseline", tuple(baseline)),
                        BenchmarkReport(spec.layer, spec.name + "-candidate", tuple(candidate)),
                    )
        return (
            BenchmarkReport(spec.layer, spec.name + "-baseline", tuple(baseline)),
            BenchmarkReport(spec.layer, spec.name + "-candidate", tuple(candidate)),
        )

    def _run_command(self, spec: BenchmarkSpec, command: tuple[str, ...]) -> BenchmarkReport:
        observations: list[BenchmarkObservation] = []
        for repetition in range(spec.repetitions):
            result = self.sandbox.run(command, timeout_seconds=spec.timeout_seconds)
            observations.append(self._observation(spec, repetition, result))
            if not result.ok:
                break
        return BenchmarkReport(spec.layer, spec.name, tuple(observations))

    @staticmethod
    def _observation(spec: BenchmarkSpec, repetition: int, result: SandboxResult) -> BenchmarkObservation:
        return BenchmarkObservation(
            spec.layer,
            spec.name,
            repetition,
            result.exit_code,
            result.duration_seconds,
            result.stdout,
            result.stderr,
            result.sandbox_id,
        )
