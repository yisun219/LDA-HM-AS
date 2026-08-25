from __future__ import annotations

from typing import Any


class OutcomeClassifier:
    def classify(self, judge: dict[str, Any], benchmark: dict[str, Any] | None = None) -> dict[str, Any]:
        benchmark = benchmark or {}
        if not judge.get("valid", False):
            category = judge.get("failure_category", "FUNCTIONAL_FAILURE")
        elif judge.get("fence_passed") is False:
            category = "ABI_FAILURE"
        elif benchmark.get("invalid"):
            category = "BENCHMARK_INVALID"
        # A numeric gain is not a releasable system result unless the
        # benchmark explicitly passed all acceptance gates (including the
        # target CPU fingerprint and E2E guardrails).  Never classify an
        # unverified measurement as SUCCESS_SYSTEM.
        elif benchmark.get("accepted") is not True:
            category = "BENCHMARK_INVALID"
        elif benchmark.get("e2e_speedup", 1.0) < 0.995:
            category = "E2E_REGRESSION"
        elif benchmark.get("e2e_speedup", 1.0) >= 1.01:
            category = "SUCCESS_SYSTEM"
        elif benchmark.get("micro_speedup", 1.0) >= 1.03:
            category = "SUCCESS_LOCAL"
        elif judge.get("capability_gap"):
            category = "CAPABILITY_GAP"
        else:
            category = "NO_OPTIMIZATION_SPACE"
        return {
            "classification": category,
            "evidence_refs": judge.get("evidence_refs", []) + benchmark.get("evidence_refs", []),
            "root_cause_category": judge.get("failure_category", ""),
            "reusable_lessons": benchmark.get("lessons", []),
            "mission_policy_updates": [],
            "capability_gap": judge.get("capability_gap"),
            "confidence": float(judge.get("confidence", 1.0)),
        }
