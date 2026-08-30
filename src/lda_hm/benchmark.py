from __future__ import annotations

import json
import math
import statistics
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Iterable

from .sandbox import Sandbox, SandboxResult
from .task_card import BenchmarkSpec

# Machine-readable sample marker emitted by in-sandbox benchmark scripts.
# Every verdict is computed from these samples; host wall time (which includes
# gateway transport) is recorded but never judged.
#
# Anti-forgery: candidate library code runs inside the measured consumer
# process and could print fake marker lines to stdout. Scripts therefore
# declare a per-invocation nonce first (LDA_BENCH_NONCE <hex>, generated in
# the script's own shell, invisible to the consumer process) and tag every
# genuine sample as LDA_BENCH[<hex>]. When a nonce is declared, untagged or
# wrongly tagged lines are ignored. The bare legacy marker is honored only
# when no nonce was declared.
BENCH_MARKER = "LDA_BENCH "
BENCH_NONCE_MARKER = "LDA_BENCH_NONCE "


class BenchmarkEnvironmentError(RuntimeError):
    """The measurement environment, not the candidate, invalidated a run.

    Callers may retry the paired run once instead of blaming the candidate.
    """


# Two-sided 95% Student-t critical values by degrees of freedom. The paired
# per-repetition ratios are few (3-9 in practice), so a normal approximation
# would understate uncertainty exactly where E2B co-tenant noise matters most.
_T95 = {
    1: 12.706, 2: 4.303, 3: 3.182, 4: 2.776, 5: 2.571, 6: 2.447, 7: 2.365,
    8: 2.306, 9: 2.262, 10: 2.228, 11: 2.201, 12: 2.179, 13: 2.160,
    14: 2.145, 15: 2.131, 20: 2.086, 25: 2.060, 30: 2.042,
}


def _t95(df: int) -> float:
    if df <= 0:
        return math.inf
    if df in _T95:
        return _T95[df]
    if df > 30:
        return 1.960
    return _T95[max(key for key in _T95 if key <= df)]


@dataclass(frozen=True)
class BenchSample:
    input: str
    seconds: float
    iterations: int = 0
    output_hash: str = ""
    load1: float = 0.0
    steal_ticks: int = 0
    cpus: int = 1


def parse_bench_samples(stdout: str) -> tuple[BenchSample, ...]:
    lines = stdout.splitlines()
    nonce = ""
    for raw in lines:
        line = raw.strip()
        if line.startswith(BENCH_NONCE_MARKER):
            # First declaration wins; a consumer process cannot pre-empt the
            # script's own first line of output.
            nonce = line[len(BENCH_NONCE_MARKER):].strip()
            break
    marker = f"LDA_BENCH[{nonce}] " if nonce else BENCH_MARKER
    samples: list[BenchSample] = []
    for raw in lines:
        line = raw.strip()
        if not line.startswith(marker):
            continue
        try:
            value = json.loads(line[len(marker):])
        except json.JSONDecodeError:
            continue
        if not isinstance(value, dict):
            continue
        try:
            seconds = float(value["seconds"])
            sample = BenchSample(
                input=str(value["input"]),
                seconds=seconds,
                iterations=int(value.get("iterations", 0)),
                output_hash=str(value.get("hash", "")),
                load1=float(value.get("load1", 0.0)),
                steal_ticks=int(value.get("steal_ticks", 0)),
                cpus=max(1, int(value.get("cpus", 1))),
            )
        except (KeyError, TypeError, ValueError):
            continue
        if seconds <= 0:
            continue
        samples.append(sample)
    return tuple(samples)


@dataclass(frozen=True)
class BenchmarkObservation:
    layer: str
    name: str
    repetition: int
    exit_code: int
    duration_seconds: float
    sandbox_id: str
    samples: tuple[BenchSample, ...] = ()
    stdout_tail: str = ""
    stderr_tail: str = ""

    @property
    def measured_seconds(self) -> float:
        return sum(sample.seconds for sample in self.samples)

    def seconds_by_input(self) -> dict[str, float]:
        totals: dict[str, float] = {}
        for sample in self.samples:
            totals[sample.input] = totals.get(sample.input, 0.0) + sample.seconds
        return totals


@dataclass(frozen=True)
class BenchmarkReport:
    layer: str
    name: str
    observations: tuple[BenchmarkObservation, ...]

    @property
    def successful(self) -> bool:
        return bool(self.observations) and all(x.exit_code == 0 for x in self.observations)

    @property
    def instrumented(self) -> bool:
        return bool(self.observations) and all(x.samples for x in self.observations)

    @property
    def median_seconds(self) -> float:
        if self.instrumented:
            return statistics.median(x.measured_seconds for x in self.observations)
        return statistics.median(x.duration_seconds for x in self.observations)

    def write(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        value = asdict(self) | {
            "successful": self.successful,
            "instrumented": self.instrumented,
            "median_seconds": self.median_seconds,
        }
        path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")


@dataclass(frozen=True)
class InputComparison:
    baseline_median_seconds: float
    candidate_median_seconds: float
    ratio_of_medians: float
    speedup_percent: float
    rep_ratio_min: float
    rep_ratio_max: float


@dataclass(frozen=True)
class PairedComparison:
    """Pure measurement summary; pass/fail policy lives with the caller."""

    layer: str
    name: str
    repetitions: int
    baseline_total_median: float
    candidate_total_median: float
    overall_ratio_median: float
    overall_speedup_percent: float
    noise_percent: float
    baseline_drift_percent: float
    max_load1: float
    max_steal_ticks: int
    # 95% Student-t interval on the mean log per-repetition ratio. With fewer
    # than three repetitions the interval is unbounded and nothing certifies.
    ratio_ci95_lower: float = 0.0
    ratio_ci95_upper: float = math.inf
    speedup_ci95_lower_percent: float = -math.inf
    # Worst per-sample fraction of CPU time stolen by co-tenants.
    max_steal_fraction: float = 0.0
    per_input: dict[str, InputComparison] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        value = asdict(self)
        value["per_input"] = {name: asdict(entry) for name, entry in self.per_input.items()}
        for key in ("ratio_ci95_lower", "ratio_ci95_upper", "speedup_ci95_lower_percent"):
            if not math.isfinite(value[key]):
                value[key] = None
        return value


def compare_paired(
    spec: BenchmarkSpec,
    baseline: BenchmarkReport,
    candidate: BenchmarkReport,
) -> PairedComparison:
    if not (baseline.successful and candidate.successful):
        raise ValueError(f"benchmark {spec.layer}/{spec.name} has failed observations")
    if not (baseline.instrumented and candidate.instrumented):
        raise ValueError(
            f"benchmark {spec.layer}/{spec.name} is not instrumented: "
            "no in-sandbox LDA_BENCH samples were emitted"
        )
    if len(baseline.observations) != len(candidate.observations):
        raise ValueError(f"benchmark {spec.layer}/{spec.name} repetition counts differ")

    pairs = list(zip(baseline.observations, candidate.observations))
    input_names = set()
    for base_obs, cand_obs in pairs:
        base_inputs = set(base_obs.seconds_by_input())
        cand_inputs = set(cand_obs.seconds_by_input())
        if base_inputs != cand_inputs:
            raise ValueError(
                f"benchmark {spec.layer}/{spec.name} input sets differ between modes"
            )
        input_names.update(base_inputs)
        _require_equivalent_hashes(spec, base_obs, cand_obs)

    total_ratios: list[float] = []
    baseline_totals: list[float] = []
    for base_obs, cand_obs in pairs:
        base_total = base_obs.measured_seconds
        cand_total = cand_obs.measured_seconds
        if base_total <= 0 or cand_total <= 0:
            raise ValueError(f"benchmark {spec.layer}/{spec.name} produced non-positive time")
        baseline_totals.append(base_total)
        total_ratios.append(cand_total / base_total)

    overall_ratio = statistics.median(total_ratios)
    noise_percent = (max(total_ratios) - min(total_ratios)) / 2.0 * 100.0
    baseline_total_median = statistics.median(baseline_totals)
    drift_percent = (
        (max(baseline_totals) - min(baseline_totals)) / baseline_total_median * 100.0
    )

    log_ratios = [math.log(ratio) for ratio in total_ratios]
    if len(log_ratios) >= 3:
        mean_log = statistics.fmean(log_ratios)
        halfwidth = _t95(len(log_ratios) - 1) * (
            statistics.stdev(log_ratios) / math.sqrt(len(log_ratios))
        )
        ratio_ci95_lower = math.exp(mean_log - halfwidth)
        ratio_ci95_upper = math.exp(mean_log + halfwidth)
    else:
        ratio_ci95_lower, ratio_ci95_upper = 0.0, math.inf
    speedup_ci95_lower_percent = (
        (1.0 / ratio_ci95_upper - 1.0) * 100.0 if ratio_ci95_upper > 0 else -math.inf
    )

    per_input: dict[str, InputComparison] = {}
    for name in sorted(input_names):
        base_values = [obs.seconds_by_input()[name] for obs, _ in pairs]
        cand_values = [obs.seconds_by_input()[name] for _, obs in pairs]
        rep_ratios = [c / b for b, c in zip(base_values, cand_values)]
        base_median = statistics.median(base_values)
        cand_median = statistics.median(cand_values)
        ratio = cand_median / base_median
        per_input[name] = InputComparison(
            baseline_median_seconds=base_median,
            candidate_median_seconds=cand_median,
            ratio_of_medians=ratio,
            speedup_percent=(1.0 / ratio - 1.0) * 100.0,
            rep_ratio_min=min(rep_ratios),
            rep_ratio_max=max(rep_ratios),
        )

    all_samples = [
        sample
        for report in (baseline, candidate)
        for obs in report.observations
        for sample in obs.samples
    ]
    return PairedComparison(
        layer=spec.layer,
        name=spec.name,
        repetitions=len(pairs),
        baseline_total_median=baseline_total_median,
        candidate_total_median=statistics.median(
            obs.measured_seconds for obs in candidate.observations
        ),
        overall_ratio_median=overall_ratio,
        overall_speedup_percent=(1.0 / overall_ratio - 1.0) * 100.0,
        noise_percent=noise_percent,
        baseline_drift_percent=drift_percent,
        max_load1=max((s.load1 for s in all_samples), default=0.0),
        max_steal_ticks=max((s.steal_ticks for s in all_samples), default=0),
        ratio_ci95_lower=ratio_ci95_lower,
        ratio_ci95_upper=ratio_ci95_upper,
        speedup_ci95_lower_percent=speedup_ci95_lower_percent,
        # Steal ticks come from the machine-wide /proc/stat aggregate, so the
        # per-sample fraction normalizes by vCPU count as well as wall time.
        max_steal_fraction=max(
            (
                (sample.steal_ticks / 100.0) / (sample.seconds * sample.cpus)
                for sample in all_samples
                if sample.seconds > 0
            ),
            default=0.0,
        ),
        per_input=per_input,
    )


def _require_equivalent_hashes(
    spec: BenchmarkSpec,
    base_obs: BenchmarkObservation,
    cand_obs: BenchmarkObservation,
) -> None:
    """Same fixture must decode to the same output in both modes."""
    base_hashes = {(s.input, s.iterations): s.output_hash for s in base_obs.samples if s.output_hash}
    for sample in cand_obs.samples:
        if not sample.output_hash:
            continue
        expected = base_hashes.get((sample.input, sample.iterations))
        if expected is not None and expected != sample.output_hash:
            raise ValueError(
                f"benchmark {spec.layer}/{spec.name} output mismatch on input "
                f"{sample.input}: baseline={expected} candidate={sample.output_hash}"
            )


class BenchmarkRunner:
    def __init__(self, sandbox: Sandbox) -> None:
        self.sandbox = sandbox

    def run(self, spec: BenchmarkSpec, *, envs: dict[str, str] | None = None) -> BenchmarkReport:
        return self._run_command(spec, spec.command, envs=envs)

    def run_baseline(self, spec: BenchmarkSpec, *, envs: dict[str, str] | None = None) -> BenchmarkReport:
        return self._run_command(spec, spec.baseline_command or spec.command, envs=envs)

    def run_paired(
        self,
        spec: BenchmarkSpec,
        *,
        envs: dict[str, str] | None = None,
    ) -> tuple[BenchmarkReport, BenchmarkReport]:
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
                result = self.sandbox.run(
                    tuple(command), timeout_seconds=spec.timeout_seconds, envs=envs
                )
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

    def run_null(
        self,
        spec: BenchmarkSpec,
        *,
        envs: dict[str, str] | None = None,
        repetitions: int | None = None,
    ) -> tuple[BenchmarkReport, BenchmarkReport]:
        """Measure the baseline against itself: an A-A calibration run.

        The true effect here is exactly zero, so whatever this run reports is
        the instrument talking, not the candidate. It is the only measurement
        in the suite whose correct answer is known in advance, which makes it
        the one that can falsify the harness rather than the patch.
        """
        baseline_command = spec.baseline_command or spec.command
        reps = spec.repetitions if repetitions is None else repetitions
        left: list[BenchmarkObservation] = []
        right: list[BenchmarkObservation] = []
        for repetition in range(reps):
            # Same order-alternation as the real pairing, so any order effect
            # this run exposes is the one the real pairing would suffer.
            ordered = (
                (left, right) if repetition % 2 == 0 else (right, left)
            )
            for target in ordered:
                result = self.sandbox.run(
                    tuple(baseline_command),
                    timeout_seconds=spec.timeout_seconds,
                    envs=envs,
                )
                target.append(self._observation(spec, repetition, result))
                if not result.ok:
                    return (
                        BenchmarkReport(spec.layer, spec.name + "-nullA", tuple(left)),
                        BenchmarkReport(spec.layer, spec.name + "-nullB", tuple(right)),
                    )
        return (
            BenchmarkReport(spec.layer, spec.name + "-nullA", tuple(left)),
            BenchmarkReport(spec.layer, spec.name + "-nullB", tuple(right)),
        )

    def _run_command(
        self,
        spec: BenchmarkSpec,
        command: Iterable[str],
        *,
        envs: dict[str, str] | None = None,
    ) -> BenchmarkReport:
        observations: list[BenchmarkObservation] = []
        for repetition in range(spec.repetitions):
            result = self.sandbox.run(
                tuple(command), timeout_seconds=spec.timeout_seconds, envs=envs
            )
            observations.append(self._observation(spec, repetition, result))
            if not result.ok:
                break
        return BenchmarkReport(spec.layer, spec.name, tuple(observations))

    @staticmethod
    def _observation(spec: BenchmarkSpec, repetition: int, result: SandboxResult) -> BenchmarkObservation:
        return BenchmarkObservation(
            layer=spec.layer,
            name=spec.name,
            repetition=repetition,
            exit_code=result.exit_code,
            duration_seconds=result.duration_seconds,
            sandbox_id=result.sandbox_id,
            samples=parse_bench_samples(result.stdout),
            stdout_tail=result.stdout[-2000:],
            stderr_tail=result.stderr[-2000:],
        )
