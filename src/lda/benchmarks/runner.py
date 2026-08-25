from __future__ import annotations

import math
import statistics
from dataclasses import dataclass
from typing import Callable, Iterable


@dataclass(frozen=True)
class BenchmarkConfig:
    warmups: int = 10
    samples: int = 30
    min_micro_speedup: float = 1.03
    min_micro_ci_lower: float = 1.01
    max_e2e_regression: float = 0.005


class BenchmarkRunner:
    def __init__(self, config: BenchmarkConfig | None = None):
        self.config = config or BenchmarkConfig()

    def measure(self, baseline: Iterable[float], candidate: Iterable[float], *, kind: str = "micro") -> dict:
        base, cand = list(baseline), list(candidate)
        if len(base) < 2 or len(cand) < 2 or any(x <= 0 for x in base + cand):
            return {"invalid": True, "reason": "insufficient_or_nonpositive_samples", "kind": kind}
        # Throughput speedup is baseline time divided by candidate time.
        speedup = statistics.mean(base) / statistics.mean(cand)
        ratios = [a / b for a, b in zip(base, cand)]
        mean = statistics.mean(ratios)
        stdev = statistics.stdev(ratios) if len(ratios) > 1 else 0.0
        ci_lower = mean - 1.96 * stdev / math.sqrt(len(ratios))
        result = {"invalid": False, "kind": kind, "samples": len(ratios), "speedup": speedup,
                  "ci_lower": ci_lower, "raw_baseline": base, "raw_candidate": cand}
        if kind == "micro":
            result["accepted"] = speedup >= self.config.min_micro_speedup and ci_lower >= self.config.min_micro_ci_lower
        else:
            result["accepted"] = speedup >= 1.0 - self.config.max_e2e_regression
        return result

    def portfolio(self, workloads: dict[str, float]) -> dict:
        if not workloads or any(v <= 0 for v in workloads.values()):
            return {"invalid": True, "geomean_speedup": 0.0, "improved_workloads": 0}
        geomean = math.prod(workloads.values()) ** (1 / len(workloads))
        return {"invalid": False, "geomean_speedup": geomean,
                "improved_workloads": sum(v > 1.0 for v in workloads.values()), "workloads": workloads}

