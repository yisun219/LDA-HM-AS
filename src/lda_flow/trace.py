"""Trace audit over actual tool/process command events only."""

from __future__ import annotations

import json
import shlex
from dataclasses import dataclass
from pathlib import Path

from .security import redact


@dataclass(frozen=True)
class TraceFinding:
    severity: str
    message: str
    command: str = ""


def audit_trace(
    path: Path, protected: tuple[str, ...], forbidden_flags: tuple[str, ...]
) -> tuple[TraceFinding, ...]:
    findings: list[TraceFinding] = []
    if not path.exists():
        return (TraceFinding("P0", "trace file missing"),)
    for line in path.read_text(encoding="utf-8").splitlines():
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            findings.append(TraceFinding("P0", "invalid trace JSON"))
            continue
        if event.get("kind") not in {"tool", "process", "command", "exec"}:
            continue
        command = redact(str(event.get("command", event.get("text", ""))))
        for flag in forbidden_flags:
            if flag in command:
                findings.append(TraceFinding("P0", f"forbidden CPU flag: {flag}", command))
        try:
            tokens = shlex.split(command)
        except ValueError:
            tokens = command.split()
        destructive = {"rm", "git-rm", "unlink", "truncate", "mv"}
        for item in protected:
            touches = any(
                token == item or token.startswith(item.rstrip("/") + "/")
                for token in tokens
            )
            if touches and any(token in destructive for token in tokens):
                findings.append(TraceFinding("P0", f"protected path deletion: {item}", command))
    return tuple(findings)
