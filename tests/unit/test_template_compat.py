from __future__ import annotations

import pytest

from lda.e2b.template_compat import configure_template_build_compatibility


def test_template_build_compat_accepts_rendered_gateway_step() -> None:
    from e2b.template_sync import build_api

    configure_template_build_compatibility()
    assert build_api.get_build_step_index("RUN apt-get update", 4) == 0
    assert build_api.get_build_step_index("2", 4) == 2
    with pytest.raises(ValueError):
        build_api.get_build_step_index("not-a-build-step", 4)
