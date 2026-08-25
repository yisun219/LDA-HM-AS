from __future__ import annotations

import importlib.metadata
import logging
import os
from threading import Lock


_LOCK = Lock()
_PATCHED = False


def configure_shared_gateway(logger: logging.Logger | None = None) -> bool:
    """Install the sole Fact-Lab shared-gateway SDK adapter."""

    global _PATCHED
    if os.getenv("E2B_API_URL") != os.getenv("E2B_SANDBOX_URL"):
        return False
    with _LOCK:
        if _PATCHED:
            return True
        from e2b.connection_config import ConnectionConfig

        descriptor = getattr(ConnectionConfig, "sandbox_headers", None)
        if not isinstance(descriptor, property) or descriptor.fget is None:
            raise RuntimeError("e2b ConnectionConfig.sandbox_headers property is unavailable")
        original_getter = descriptor.fget
        if getattr(original_getter, "_lda_shared_gateway", False):
            _PATCHED = True
            return True

        def sandbox_headers(config: ConnectionConfig) -> dict[str, str]:
            headers = dict(original_getter(config))
            if not config.api_key:
                raise RuntimeError("E2B API key is required by the shared gateway")
            headers["X-API-KEY"] = config.api_key
            return headers

        setattr(sandbox_headers, "_lda_shared_gateway", True)
        ConnectionConfig.sandbox_headers = property(
            sandbox_headers,
            descriptor.fset,
            descriptor.fdel,
            descriptor.__doc__,
        )
        _PATCHED = True
        (logger or logging.getLogger(__name__)).info(
            "configured E2B shared gateway for SDK %s",
            importlib.metadata.version("e2b"),
        )
        return True
