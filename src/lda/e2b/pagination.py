from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any


async def iterate_pages(paginator: Any) -> AsyncIterator[Any]:
    """Yield items from E2B 2.45 paginators and lightweight test iterators."""

    if hasattr(paginator, "next_items") and hasattr(paginator, "has_next"):
        while paginator.has_next:
            for item in await paginator.next_items():
                yield item
        return
    async for item in paginator:
        yield item
