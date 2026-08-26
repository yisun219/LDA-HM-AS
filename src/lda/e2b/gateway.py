from __future__ import annotations

import os
import re
import threading
from importlib import metadata
from dataclasses import dataclass
from typing import Any


SUPPORTED_SDK_VERSIONS = {"2.10.2"}
_PATCH_LOCK = threading.Lock()
_PATCHED = False


@dataclass(frozen=True)
class GatewayConfig:
    api_url: str = "https://e2b.fact-lab.work"
    sandbox_url: str = "https://e2b.fact-lab.work"
    access_token: str = "dummy"
    api_key_env: str = "E2B_API_KEY"
    shared_gateway: bool = True
    validate_api_key: bool = True
    api_key: str | None = None

    @classmethod
    def from_env(cls) -> "GatewayConfig":
        # Load the optional private operator file without copying its values into
        # project state, event logs, templates, or child sandbox metadata.
        private_file = os.environ.get("LDA_E2B_ENV_FILE", os.path.expanduser("~/.config/lda/e2b.env"))
        if os.path.exists(private_file):
            with open(private_file, encoding="utf-8") as fh:
                for line in fh:
                    line = line.strip()
                    if not line or line.startswith("#") or "=" not in line:
                        continue
                    key, value = line.split("=", 1)
                    key = key.strip()
                    if key.startswith("export "):
                        key = key.removeprefix("export ").strip()
                    value = value.strip().strip("\"'")
                    if value.startswith("$"):
                        value = os.environ.get(value.removeprefix("$"), value)
                    os.environ.setdefault(key, value)
        config_file = os.environ.get("LDA_CONFIG_FILE", "configs/lda.yaml")
        yaml_key = None
        if os.path.exists(config_file):
            with open(config_file, encoding="utf-8") as fh:
                match = re.search(r"^\s*api_key:\s*[\"']?([^\"'\s]+)", fh.read(), re.MULTILINE)
                yaml_key = match.group(1) if match else None
        api = os.environ.get("E2B_API_URL", cls.api_url)
        return cls(api_url=api, sandbox_url=os.environ.get("E2B_SANDBOX_URL", api),
                   access_token=os.environ.get("E2B_ACCESS_TOKEN", cls.access_token),
                   api_key=os.environ.get("E2B_API_KEY") or yaml_key)


class SharedGateway:
    """Idempotent request adapter preserving SDK headers and adding X-API-KEY once."""

    def __init__(self, config: GatewayConfig | None = None):
        self.config = config or GatewayConfig.from_env()
        self.api_key = self.config.api_key or os.environ.get(self.config.api_key_env)

    def install_sdk_adapter(self) -> bool:
        """Patch the SDK data-plane headers once for the shared gateway.

        The stock SDK constructs sandbox routing headers lazily. Replacing
        those headers at call sites can drop ``E2b-Sandbox-Id`` or
        ``E2b-Sandbox-Port``. Extending the SDK property preserves every
        original header and covers both ``Sandbox`` and ``AsyncSandbox``.
        """
        global _PATCHED
        if not self.config.shared_gateway or self.config.api_url != self.config.sandbox_url:
            return False
        if self.config.validate_api_key and not self.api_key:
            raise RuntimeError(f"{self.config.api_key_env} is required for the shared E2B gateway")
        version = metadata.version("e2b")
        if version not in SUPPORTED_SDK_VERSIONS:
            raise RuntimeError(f"unsupported E2B SDK version for shared gateway adapter: {version}")
        with _PATCH_LOCK:
            if _PATCHED:
                return True
            from e2b.connection_config import ConnectionConfig

            original_getter = ConnectionConfig.sandbox_headers.fget

            def sandbox_headers(connection: Any) -> dict[str, str]:
                headers = dict(original_getter(connection))
                headers["X-API-KEY"] = connection.api_key
                return headers

            ConnectionConfig.sandbox_headers = property(sandbox_headers)
            _PATCHED = True
        return True

    def headers(self, sdk_headers: dict[str, str] | None = None) -> dict[str, str]:
        headers = dict(sdk_headers or {})
        headers.setdefault("X-Access-Token", self.config.access_token)
        headers.setdefault("User-Agent", "linux-development-agent/0.1")
        if self.config.shared_gateway and self.config.api_url == self.config.sandbox_url:
            if self.config.validate_api_key and not self.api_key:
                raise RuntimeError(f"{self.config.api_key_env} is required for the shared E2B gateway")
            headers.setdefault("X-API-KEY", self.api_key or "")
        return headers

    def bind_sandbox(self, sandbox: Any) -> None:
        """Repair shared-gateway routing after SDK create/connect.

        E2B 2.10.2 adds the routing headers on ``create`` but omits them in
        the class-level ``connect`` reconstruction path. Apply them to the
        shared connection config and to the already-created filesystem client.
        """
        if not self.config.shared_gateway or self.config.api_url != self.config.sandbox_url:
            return
        connection = sandbox.connection_config
        routing = {
            "E2b-Sandbox-Id": sandbox.sandbox_id,
            "E2b-Sandbox-Port": str(connection.envd_port),
            "X-API-KEY": self.api_key or "",
        }
        connection.headers.update(routing)
        envd_api = getattr(sandbox, "_envd_api", None)
        if envd_api is not None:
            envd_api.headers.update(routing)

    def endpoint(self, path: str) -> str:
        return self.config.api_url.rstrip("/") + "/" + path.lstrip("/")
