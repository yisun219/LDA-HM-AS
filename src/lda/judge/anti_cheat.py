from __future__ import annotations

from typing import Any


class AntiCheat:
    KEYS = ("tests_modified", "benchmark_modified", "workload_shrunk", "hardcoded_output",
            "precision_lowered", "feature_disabled", "baseline_polluted", "ld_preload",
            "network_download", "ignored_samples", "untracked_binary")

    def inspect(self, metadata: dict[str, Any]) -> dict[str, bool]:
        return {key: bool(metadata.get(key, False)) for key in self.KEYS}

