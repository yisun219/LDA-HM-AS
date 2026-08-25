from __future__ import annotations

import os
import re
from dataclasses import dataclass
from typing import Any


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
                    os.environ.setdefault(key.strip(), value.strip().strip("\"'"))
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

    def headers(self, sdk_headers: dict[str, str] | None = None) -> dict[str, str]:
        headers = dict(sdk_headers or {})
        headers.setdefault("E2b-Sandbox-Id", headers.get("e2b-sandbox-id", ""))
        headers.setdefault("E2b-Sandbox-Port", headers.get("e2b-sandbox-port", ""))
        headers.setdefault("X-Access-Token", self.config.access_token)
        headers.setdefault("User-Agent", "lda-autoresearch/0.1")
        if self.config.shared_gateway and self.config.api_url == self.config.sandbox_url:
            if self.config.validate_api_key and not self.api_key:
                raise RuntimeError(f"{self.config.api_key_env} is required for the shared E2B gateway")
            headers.setdefault("X-API-KEY", self.api_key or "")
        return headers

    def endpoint(self, path: str) -> str:
        return self.config.api_url.rstrip("/") + "/" + path.lstrip("/")
