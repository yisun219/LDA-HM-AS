#!/usr/bin/env python3
from __future__ import annotations

import json
import re
import sys
from pathlib import Path


FORBIDDEN = (
    r"bypass[_ -]?fence",
    r"git\s+push\s+--force",
    r"git\s+add\s+.*\.lda-hm",
    r"(?:rm|truncate)\s+.*(?:evidence|task-card|state\.json)",
    r"(?:sed\s+-i|perl\s+-pi).*?(?:task-card|state\.json|plan\.md)",
)


def strings(value):
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for item in value.values():
            yield from strings(item)
    elif isinstance(value, list):
        for item in value:
            yield from strings(item)


def main() -> int:
    path = Path(sys.argv[1])
    if not path.is_file() or path.stat().st_size == 0:
        print("trace missing or empty", file=sys.stderr)
        return 2
    for number, line in enumerate(path.read_text(encoding="utf-8", errors="replace").splitlines(), 1):
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        combined = "\n".join(strings(event))
        for pattern in FORBIDDEN:
            if re.search(pattern, combined, re.IGNORECASE):
                print(f"forbidden trace behavior at line {number}: {pattern}", file=sys.stderr)
                return 3
    print(f"trace audit passed: {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
