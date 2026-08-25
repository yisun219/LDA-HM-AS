#!/usr/bin/env python3
"""Trace fixture validator: inspect command events, never ordinary prompt text."""

import json
import sys
from pathlib import Path


def main(path: str) -> int:
    events = [json.loads(line) for line in Path(path).read_text().splitlines()]
    commands = [
        event.get("command", "")
        for event in events
        if event.get("kind") in {"tool", "process", "command", "exec"}
    ]
    bad = [
        command
        for command in commands
        if "-march=native" in command or "-march=sapphirerapids" in command
    ]
    print(json.dumps({"commands_checked": len(commands), "forbidden_commands": bad}))
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1]))
