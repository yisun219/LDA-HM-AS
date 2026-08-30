"""The A-A calibration gate must falsify a harness that invents effects."""
import pytest

from lda_hm.benchmark import (
    BenchmarkObservation,
    BenchmarkReport,
    BenchmarkRunner,
    compare_paired,
    parse_bench_samples,
)
from lda_hm.execution import BenchmarkEnvironmentError, judge_null_run
from lda_hm.sandbox import SandboxResult
from lda_hm.task_card import BenchmarkSpec


def _spec(min_speedup: float | None = 2.0) -> BenchmarkSpec:
    return BenchmarkSpec(
        name="calib",
        layer="micro",
        command=("./micro", "candidate"),
        baseline_command=("./micro", "baseline"),
        repetitions=5,
        max_regression_percent=2.0,
        min_speedup_percent=min_speedup,
    )


def _line(seconds: float) -> str:
    return (
        'LDA_BENCH {"input":"only","seconds":%s,"iterations":1,'
        '"hash":"h","load1":0.1,"steal_ticks":0,"cpus":8}' % seconds
    )


def _report(name: str, seconds: list[float]) -> BenchmarkReport:
    observations = tuple(
        BenchmarkObservation(
            layer="micro",
            name=name,
            repetition=repetition,
            exit_code=0,
            duration_seconds=value + 0.4,
            sandbox_id="fake",
            samples=parse_bench_samples(_line(value)),
        )
        for repetition, value in enumerate(seconds)
    )
    return BenchmarkReport("micro", name, observations)


def _compare(left: list[float], right: list[float]):
    return compare_paired(_spec(), _report("nullA", left), _report("nullB", right))


def test_clean_null_run_passes():
    """Symmetric jitter around a true zero effect must not block anything."""
    left = [1.000, 1.004, 0.997, 1.003, 0.996]
    right = [1.002, 0.998, 1.001, 0.999, 1.000]
    judge_null_run(_spec(), _compare(left, right), 2.0, stage="test")


def test_phantom_certified_effect_is_rejected():
    """A-A resolving a consistent difference means the harness lies."""
    left = [1.000, 1.001, 0.999, 1.000, 1.001]
    right = [0.940, 0.941, 0.939, 0.940, 0.941]
    comparison = _compare(left, right)
    assert comparison.ratio_ci95_upper < 1.0, "fixture must resolve a phantom effect"
    with pytest.raises(BenchmarkEnvironmentError, match="phantom effect"):
        judge_null_run(_spec(), comparison, 2.0, stage="test")


def test_bias_above_half_the_target_is_rejected():
    """An apparent effect too close to the target cannot be told from it."""
    left = [1.000, 1.002, 0.998, 1.001, 0.999]
    right = [0.900, 1.062, 0.948, 1.021, 0.939]
    comparison = _compare(left, right)
    assert comparison.ratio_ci95_upper >= 1.0, "fixture must stay unresolved"
    with pytest.raises(BenchmarkEnvironmentError, match="bias too large"):
        judge_null_run(_spec(), comparison, 2.0, stage="test")


def test_regression_only_benchmark_is_not_calibrated():
    """No speedup target means no claim to calibrate against."""
    left = [1.000, 1.001, 0.999, 1.000, 1.001]
    right = [0.940, 0.941, 0.939, 0.940, 0.941]
    judge_null_run(_spec(None), _compare(left, right), None, stage="test")


def test_run_null_pairs_the_baseline_against_itself():
    """Both sides of the calibration must run the baseline command."""

    class _Recorder:
        sandbox_id = "fake"

        def __init__(self) -> None:
            self.calls: list[tuple[str, ...]] = []

        def run(self, command, timeout_seconds=None, envs=None):
            self.calls.append(tuple(command))
            return SandboxResult(
                command=tuple(command),
                exit_code=0,
                stdout=_line(1.0),
                stderr="",
                duration_seconds=1.4,
                sandbox_id="fake",
            )

    recorder = _Recorder()
    left, right = BenchmarkRunner(recorder).run_null(_spec(), repetitions=4)
    assert len(recorder.calls) == 8
    assert set(recorder.calls) == {("./micro", "baseline")}
    assert len(left.observations) == 4
    assert len(right.observations) == 4
