"""Deterministic benchmark statistics and reward calculation."""

from __future__ import annotations

import math
import statistics
from dataclasses import dataclass


@dataclass(frozen=True)
class BenchmarkResult:
    name: str
    baseline: tuple[float, ...]
    candidate: tuple[float, ...]
    baseline_median: float
    candidate_median: float
    mad: float
    speedup: float
    passed: bool
    reward: float


def summarize(
    name: str,
    baseline: tuple[float, ...],
    candidate: tuple[float, ...],
    *,
    lower_is_better: bool,
    max_relative_mad: float,
    min_speedup: float,
) -> BenchmarkResult:
    if (
        not baseline
        or not candidate
        or any(not math.isfinite(x) or x <= 0 for x in (*baseline, *candidate))
    ):
        return BenchmarkResult(name, baseline, candidate, 0, 0, math.inf, 0, False, 0)
    bm, cm = statistics.median(baseline), statistics.median(candidate)
    mad = statistics.median([abs(x - cm) for x in candidate]) / cm
    speedup = bm / cm if lower_is_better else cm / bm
    passed = mad <= max_relative_mad and speedup >= min_speedup
    reward = speedup if passed else 0.0
    return BenchmarkResult(name, baseline, candidate, bm, cm, mad, speedup, passed, reward)


def geomean(values: tuple[float, ...]) -> float:
    if not values or any(value <= 0 for value in values):
        return 0.0
    return math.exp(sum(math.log(value) for value in values) / len(values))
