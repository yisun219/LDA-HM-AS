"""Credential forwarding and report redaction."""

from __future__ import annotations

import os
import re

ALLOWED_CREDENTIALS = frozenset(
    {"OPENAI_API_KEY", "ANTHROPIC_API_KEY", "DEEPSEEK_API_KEY", "DEEPSEEK_BASE_URL"}
)
SECRET_NAMES = frozenset({"E2B_API_KEY", "E2B_ACCESS_TOKEN", *ALLOWED_CREDENTIALS})


def forwarded_environment(names: tuple[str, ...]) -> dict[str, str]:
    unknown = set(names) - ALLOWED_CREDENTIALS
    if unknown:
        raise ValueError(f"credential is not allowlisted: {sorted(unknown)}")
    return {name: os.environ[name] for name in names if os.environ.get(name)}


def redact(text: str) -> str:
    result = text
    for name in SECRET_NAMES:
        value = os.environ.get(name)
        if value:
            result = result.replace(value, "[REDACTED]")
    return re.sub(r"(?i)(api[_-]?key|access[_-]?token)\s*[:=]\s*\S+", r"\1=[REDACTED]", result)
