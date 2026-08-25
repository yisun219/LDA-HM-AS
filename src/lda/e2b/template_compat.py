from __future__ import annotations

from threading import Lock


_LOCK = Lock()
_CONFIGURED = False


def configure_template_build_compatibility() -> bool:
    """Accept Fact-Lab build failures whose step is the rendered RUN command.

    E2B 2.45 expects ``reason.step`` to be a numeric layer index, while the
    shared gateway returns the rendered instruction for some failures.  The
    mismatch otherwise masks the useful remote error with a local ValueError.
    """

    global _CONFIGURED
    with _LOCK:
        if _CONFIGURED:
            return False

        from e2b.template_sync import build_api

        original = build_api.get_build_step_index
        if not callable(original):
            raise RuntimeError("E2B template build step parser is unavailable")

        def compatible_step_index(step: str, stack_traces_length: int) -> int:
            try:
                return original(step, stack_traces_length)
            except ValueError:
                if step.startswith(("RUN ", "COPY ", "ENV ", "WORKDIR ", "USER ")):
                    return 0
                raise

        build_api.get_build_step_index = compatible_step_index
        _CONFIGURED = True
        return True
