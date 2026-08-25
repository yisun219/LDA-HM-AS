from __future__ import annotations

import math
import random
import statistics
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, model_validator

from lda.config import BenchmarkConfig


class BenchmarkDecision(StrEnum):
    PASS = "PASS"
    FAIL = "FAIL"
    INVALID = "INVALID"


class BenchmarkSeries(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    name: str
    layer: str
    baseline: list[float] = Field(min_length=30)
    candidate: list[float] = Field(min_length=30)
    warmups: int = Field(ge=10)
    seed: int
    randomized_order: list[str]
    cpu_affinity: str
    numa_policy: str
    environment: dict[str, str]

    @model_validator(mode="after")
    def paired(self) -> "BenchmarkSeries":
        if len(self.baseline) != len(self.candidate):
            raise ValueError("benchmark series must be paired")
        if len(self.randomized_order) != len(self.baseline):
            raise ValueError("benchmark order count does not match samples")
        if any(value <= 0 or not math.isfinite(value) for value in (*self.baseline, *self.candidate)):
            raise ValueError("benchmark samples must be positive finite durations")
        return self


class BenchmarkComparison(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    name: str
    layer: str
    paired_geomean_ratio: float
    ci_lower: float
    ci_upper: float
    baseline_cv: float
    candidate_cv: float
    decision: BenchmarkDecision
    reason: str


def _cv(values: list[float]) -> float:
    mean = statistics.fmean(values)
    return statistics.stdev(values) / mean if len(values) > 1 else 0.0


def _geomean(values: list[float]) -> float:
    return math.exp(statistics.fmean(math.log(value) for value in values))


def compare_paired(series: BenchmarkSeries, config: BenchmarkConfig, *, bootstrap_samples: int = 10_000) -> BenchmarkComparison:
    ratios = [baseline / candidate for baseline, candidate in zip(series.baseline, series.candidate, strict=True)]
    ratio = _geomean(ratios)
    baseline_cv = _cv(series.baseline)
    candidate_cv = _cv(series.candidate)
    rng = random.Random(series.seed)
    estimates: list[float] = []
    for _ in range(bootstrap_samples):
        sample = [ratios[rng.randrange(len(ratios))] for _ in ratios]
        estimates.append(_geomean(sample))
    estimates.sort()
    ci_lower = estimates[int(bootstrap_samples * 0.025)]
    ci_upper = estimates[min(bootstrap_samples - 1, int(bootstrap_samples * 0.975))]
    if max(baseline_cv, candidate_cv) > config.max_noise_cv:
        decision, reason = BenchmarkDecision.INVALID, "coefficient of variation exceeds noise limit"
    elif series.layer == "micro" and (ratio < config.min_micro_speedup or ci_lower < config.min_micro_ci_lower):
        decision, reason = BenchmarkDecision.FAIL, "micro speedup or confidence interval is below policy"
    elif series.layer == "e2e" and ci_upper < 1.0 - config.max_e2e_regression:
        decision, reason = BenchmarkDecision.FAIL, "E2E regression exceeds policy"
    else:
        decision, reason = BenchmarkDecision.PASS, "benchmark satisfies policy"
    return BenchmarkComparison(
        name=series.name,
        layer=series.layer,
        paired_geomean_ratio=ratio,
        ci_lower=ci_lower,
        ci_upper=ci_upper,
        baseline_cv=baseline_cv,
        candidate_cv=candidate_cv,
        decision=decision,
        reason=reason,
    )


def portfolio_decision(comparisons: list[BenchmarkComparison], config: BenchmarkConfig) -> bool:
    e2e = [item for item in comparisons if item.layer == "e2e" and item.decision is BenchmarkDecision.PASS]
    if len(e2e) < config.min_improved_e2e_workloads:
        return False
    improved = [item for item in e2e if item.ci_lower > 1.0]
    return (
        len(improved) >= config.min_improved_e2e_workloads
        and _geomean([item.paired_geomean_ratio for item in e2e]) >= config.portfolio_min_geomean_speedup
    )
