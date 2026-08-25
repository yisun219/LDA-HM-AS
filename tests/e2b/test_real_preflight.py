import os

import pytest

from lda.config import LDAConfig
from lda.e2b.preflight import run_preflight


pytestmark = pytest.mark.skipif(os.getenv("LDA_REAL_E2B") != "1", reason="real E2B test")


async def test_real_e2b_preflight() -> None:
    config = LDAConfig.load()
    report = await run_preflight(config.e2b)
    assert report.snapshot_id
    assert report.background_pid
    assert report.checks["metadata"] == "ok"
