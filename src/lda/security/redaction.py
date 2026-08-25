from __future__ import annotations

import os
import re
from collections.abc import Mapping


FORBIDDEN_CHILD_ENV = frozenset(
    {
        "E2B_API_KEY",
        "E2B_ACCESS_TOKEN",
        "E2B_API_URL",
        "E2B_SANDBOX_URL",
        "CODEX_API_KEY",
        "OPENAI_API_KEY",
        "ANTHROPIC_API_KEY",
        "ANTHROPIC_AUTH_TOKEN",
    }
)


def child_environment(source: Mapping[str, str] | None = None, *, agent_runtime: bool = False) -> dict[str, str]:
    environment = dict(source or os.environ)
    allowed_agent_secrets = {"LDA_CODEX_API_KEY"} if agent_runtime else set()
    for key in FORBIDDEN_CHILD_ENV:
        environment.pop(key, None)
    for key in tuple(environment):
        upper = key.upper()
        if key not in allowed_agent_secrets and (upper.endswith("_API_KEY") or upper.endswith("_ACCESS_TOKEN")):
            environment.pop(key, None)
    return environment


class SecretRedactor:
    _patterns = (
        re.compile(r"\be2b_[A-Za-z0-9_-]{16,}\b"),
        re.compile(r"\bsk-[A-Za-z0-9_-]{16,}\b"),
        re.compile(r"(?i)(api[_-]?key|access[_-]?token|authorization)\s*[:=]\s*[^\s,;]+"),
    )

    def __init__(self, explicit: list[str] | None = None) -> None:
        self.explicit = sorted((value for value in (explicit or []) if value), key=len, reverse=True)

    def redact(self, value: str) -> str:
        redacted = value
        for secret in self.explicit:
            redacted = redacted.replace(secret, "[REDACTED]")
        for pattern in self._patterns:
            redacted = pattern.sub("[REDACTED]", redacted)
        return redacted

    def assert_clean(self, value: str) -> None:
        if self.redact(value) != value:
            raise ValueError("secret material detected")
