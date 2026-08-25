"""E2B-only gateway. No host or Docker fallback exists."""

from __future__ import annotations

import os
from dataclasses import dataclass

from .models import E2BSettings
from .security import forwarded_environment


class GatewayError(RuntimeError):
    pass


def configure_shared_gateway() -> None:
    api_url = os.getenv("E2B_API_URL")
    sandbox_url = os.getenv("E2B_SANDBOX_URL")
    if not api_url or api_url != sandbox_url:
        return
    try:
        from e2b.connection_config import ConnectionConfig
    except ImportError as exc:
        raise GatewayError("E2B SDK is required") from exc
    original_getter = ConnectionConfig.sandbox_headers.fget
    if original_getter is None:
        raise GatewayError("E2B SDK sandbox header API changed")

    def sandbox_headers(config):
        headers = dict(original_getter(config))
        headers["X-API-KEY"] = config.api_key
        return headers

    ConnectionConfig.sandbox_headers = property(sandbox_headers)


def require_e2b(settings: E2BSettings) -> None:
    missing = [
        name
        for name in (
            settings.api_url_env,
            settings.sandbox_url_env,
            settings.api_key_env,
            settings.access_token_env,
        )
        if not os.getenv(name)
    ]
    if missing:
        raise GatewayError("missing E2B environment: " + ", ".join(missing))


@dataclass
class SandboxHandle:
    sandbox: object
    sandbox_id: str
    template: str

    def snapshot(self) -> str:
        info = self.sandbox.create_snapshot()
        return str(getattr(info, "snapshot_id", getattr(info, "id", "unknown")))


def create_sandbox(
    settings: E2BSettings,
    forward_env: tuple[str, ...],
    snapshot_id: str | None = None,
) -> SandboxHandle:
    require_e2b(settings)
    configure_shared_gateway()
    try:
        from e2b import Sandbox
    except ImportError as exc:
        raise GatewayError("install e2b==2.15.0") from exc
    environment = forwarded_environment(forward_env)
    sandbox = Sandbox.create(
        template=snapshot_id or settings.template,
        timeout=settings.timeout_seconds,
        envs=environment,
    )
    sandbox_id = str(getattr(sandbox, "sandbox_id", getattr(sandbox, "id", "unknown")))
    return SandboxHandle(sandbox, sandbox_id, snapshot_id or settings.template)
