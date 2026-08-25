from __future__ import annotations

import re
from typing import Any


SECRET_KEYS = {"E2B_API_KEY", "E2B_ACCESS_TOKEN", "OPENAI_API_KEY", "CODEX_API_KEY", "api_key", "access_token"}


def redact(value: Any) -> Any:
    if isinstance(value, dict):
        return {k: "[REDACTED]" if k in SECRET_KEYS else redact(v) for k, v in value.items()}
    if isinstance(value, list):
        return [redact(v) for v in value]
    if isinstance(value, str):
        return re.sub(r"(?i)(api[_-]?key|access[_-]?token)\s*[=:]\s*[^\s]+", r"\1=[REDACTED]", value)
    return value

