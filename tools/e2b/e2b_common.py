"""Shared E2B helpers for the LDA sandbox fleet.

No secrets live here. Everything is read from the environment:

    E2B_API_KEY       required
    E2B_API_URL       control-plane base URL
    E2B_SANDBOX_URL   sandbox (envd) base URL
    E2B_TEMPLATE      default template name

When E2B_API_URL == E2B_SANDBOX_URL the deployment is a shared single-host
gateway: envd traffic is proxied through the same origin as the control
plane, and that proxy authenticates with the X-API-KEY header. The stock SDK
only sends the key to the control plane, so `configure_shared_gateway()`
patches ConnectionConfig.sandbox_headers to add it. Call it once, before any
Sandbox/Template call, in every script that talks to the gateway.
"""

from __future__ import annotations

import os
import time
from typing import Any, Callable

from e2b.connection_config import ConnectionConfig

_patched = False


def configure_shared_gateway() -> bool:
    """Add X-API-KEY to sandbox-bound requests on a shared gateway.

    Returns True when the patch was applied (or already active)."""
    global _patched
    if os.getenv("E2B_API_URL") != os.getenv("E2B_SANDBOX_URL"):
        return False
    if _patched:
        return True
    original_getter = ConnectionConfig.sandbox_headers.fget

    def sandbox_headers(config: ConnectionConfig) -> dict[str, str]:
        headers = dict(original_getter(config))
        headers["X-API-KEY"] = config.api_key
        return headers

    ConnectionConfig.sandbox_headers = property(sandbox_headers)
    _patched = True
    return True


def require_env(*names: str) -> None:
    missing = [n for n in names if not os.getenv(n)]
    if missing:
        raise SystemExit(
            "missing env: %s -- source your E2B env file first" % ", ".join(missing)
        )


def default_template() -> str:
    return os.getenv("E2B_TEMPLATE", "base")


def retry(fn: Callable[[], Any], attempts: int = 2, label: str = "op") -> Any:
    """Retry discipline: at most `attempts` tries, and stop as soon as two
    failures share the same exception type (same cause twice == stop)."""
    seen: list[str] = []
    last: BaseException | None = None
    for i in range(attempts):
        try:
            return fn()
        except Exception as exc:  # noqa: BLE001 - deliberate: caller decides
            last = exc
            kind = type(exc).__name__
            if kind in seen:
                raise RuntimeError(
                    f"{label}: same failure twice ({kind}: {exc}) -- stopping"
                ) from exc
            seen.append(kind)
            if i + 1 < attempts:
                time.sleep(2.0)
    raise RuntimeError(f"{label}: exhausted {attempts} attempts") from last
