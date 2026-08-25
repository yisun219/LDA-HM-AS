from __future__ import annotations

import os


def controller_secret_env() -> dict[str, str]:
    """Only the controller receives the E2B key; values are never serialized."""
    return {key: value for key, value in os.environ.items() if key == "E2B_API_KEY"}


def agent_secret_env() -> dict[str, str]:
    """Codex credentials are scoped to the runtime process, not workspace or judge."""
    return {key: value for key, value in os.environ.items() if key in {"OPENAI_API_KEY", "CODEX_API_KEY"}}


def child_sandbox_env() -> dict[str, str]:
    return {}

