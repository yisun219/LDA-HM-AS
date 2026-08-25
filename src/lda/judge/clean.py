from __future__ import annotations

from typing import Any

from lda.fences.abi import CompatibilityFence


class CleanJudge:
    """Deterministic judge; it never imports or calls an LLM."""

    def __init__(self, fence: CompatibilityFence):
        self.fence = fence

    def run(self, candidate: dict[str, Any], *, self_test: bool = True,
            reverse_dependencies: bool = True, anti_cheat: dict[str, Any] | None = None) -> dict[str, Any]:
        fence = self.fence.check(candidate.get("manifest", candidate))
        checks = {
            "self_test": self_test,
            "reverse_dependencies": reverse_dependencies,
            "package_install": bool(candidate.get("package_install", True)),
            "rollback": bool(candidate.get("rollback", True)),
        }
        cheating = [k for k, v in (anti_cheat or {}).items() if v]
        valid = fence["passed"] and all(checks.values()) and not cheating
        return {"valid": valid, "fence_passed": fence["passed"], "fence": fence,
                "checks": checks, "anti_cheat": {"passed": not cheating, "findings": cheating},
                "failure_category": "ABI_FAILURE" if not fence["passed"] else ("ANTI_CHEAT" if cheating else ""),
                "evidence_refs": [], "confidence": 1.0}

