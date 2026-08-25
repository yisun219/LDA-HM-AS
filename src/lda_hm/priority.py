from __future__ import annotations

from .task_card import PackagePriority, rank_packages


def select_package_batch(candidates: list[PackagePriority], *, limit: int = 8) -> list[PackagePriority]:
    """Select high-value packages before any optimization card is opened."""
    return rank_packages(candidates, limit)
