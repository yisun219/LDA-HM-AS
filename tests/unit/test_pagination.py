from __future__ import annotations

from lda.e2b.pagination import iterate_pages


class SDKPaginator:
    def __init__(self) -> None:
        self.pages = [[1, 2], [3]]

    @property
    def has_next(self) -> bool:
        return bool(self.pages)

    async def next_items(self):
        return self.pages.pop(0)


async def test_sdk_paginator_pages_are_consumed() -> None:
    assert [item async for item in iterate_pages(SDKPaginator())] == [1, 2, 3]
