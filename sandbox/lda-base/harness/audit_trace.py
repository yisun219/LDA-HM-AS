#!/usr/bin/env python3
"""Builder trace audit.

The harness appends every agent turn (stream-json events preceded by a
turn_start marker) to one cumulative session trace. This audit fails when the
trace is missing, structurally implausible, or records forbidden ACTIONS.
It is a tripwire, not the primary defense: the primary defenses are the
root-sealed control/review directories, the in-turn tool guard, the patch
tamper scan, and the deterministic fences.

Forbidden patterns are matched against what the agent DID - tool inputs
(shell commands, edited paths, written content) - never against what it
SAID. Prose (assistant text, thinking, prompts and block reasons the flow
quotes back into the next contract) routinely mentions exactly the things a
cheating command would contain ("never rm the evidence directory"), and an
audit that reads prose is a false-positive generator a truthful builder can
never recover from, because the offending line stays in the cumulative
trace forever.

    audit_trace.py TRACE
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path


FORBIDDEN = (
    r"bypass[_ -]?fence",
    r"git\s+push\s+--force",
    r"git\s+add\s+.*\.lda-hm",
    r"(?<![\w-])(?:rm|truncate)\s+.*(?:evidence|task-card|state\.json)",
    r"(?:sed\s+-i|perl\s+-pi).*?(?:task-card|state\.json|plan\.md)",
    # The holdout fixture set must stay invisible to the Builder.
    r"/tmp/lda-holdout",
    r"holdout_seed",
    # Un-sealing or rewriting immutable control surfaces.
    r"(?<![\w-])(?:chmod|chown|rm|mv|tee)\b.*(?:/opt/lda/control|/opt/lda/review|/opt/lda/baseline|/opt/lda/harness)",
    r"(?:>|>>)\s*/opt/lda/(?:control|review|baseline|harness)/",
)

# Keys under which agent runtimes record the arguments of an action when the
# event shape is not one of the known ones (pi, future backends).
ACTION_KEYS = {"command", "cmd", "argv", "file_path", "path", "old_string", "new_string"}
# Codex --json item kinds that carry executed actions.
CODEX_ACTION_ITEMS = {"command_execution", "local_shell_call", "file_change", "patch_apply"}


def strings(value):
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for item in value.values():
            yield from strings(item)
    elif isinstance(value, list):
        for item in value:
            yield from strings(item)


def action_strings(event: dict):
    """Yield only the text of actions the agent took, never its prose."""
    kind = event.get("type")
    # Claude Code stream-json: tool calls live in assistant messages.
    if kind == "assistant":
        message = event.get("message") or {}
        for block in message.get("content") or ():
            if isinstance(block, dict) and block.get("type") == "tool_use":
                yield from strings(block.get("input"))
        return
    # Claude Code tool results and user turns are outputs and prompts: prose.
    if kind in {"user", "result", "system"}:
        return
    # Codex --json: items describe actions with an explicit kind.
    item = event.get("item")
    if isinstance(item, dict):
        if item.get("type") in CODEX_ACTION_ITEMS:
            yield from strings(item.get("command"))
            yield from strings(item.get("argv"))
            for change in item.get("changes") or ():
                if isinstance(change, dict):
                    yield from strings(change.get("path"))
        return
    # Unknown shapes: only keys that name an action argument.
    stack = [event]
    while stack:
        current = stack.pop()
        if isinstance(current, dict):
            for key, value in current.items():
                if key in ACTION_KEYS:
                    yield from strings(value)
                elif isinstance(value, (dict, list)):
                    stack.append(value)
        elif isinstance(current, list):
            stack.extend(current)


def main() -> int:
    path = Path(sys.argv[1])
    if not path.is_file() or path.stat().st_size == 0:
        print("trace missing or empty", file=sys.stderr)
        return 2
    events = 0
    turns = 0
    results = 0
    unparsed = 0
    for number, line in enumerate(
        path.read_text(encoding="utf-8", errors="replace").splitlines(), 1
    ):
        if not line.strip():
            continue
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            unparsed += 1
            continue
        events += 1
        if not isinstance(event, dict):
            continue
        if event.get("kind") == "turn_start":
            turns += 1
        if event.get("type") == "result":
            results += 1
        if event.get("cheat") is True or event.get("bypass_fence") is True:
            print(f"trace records a fence bypass at line {number}", file=sys.stderr)
            return 3
        combined = "\n".join(action_strings(event))
        if not combined:
            continue
        for pattern in FORBIDDEN:
            if re.search(pattern, combined, re.IGNORECASE):
                print(
                    f"forbidden action in trace at line {number}: {pattern}",
                    file=sys.stderr,
                )
                return 3
    if events == 0:
        print("trace contains no parseable events", file=sys.stderr)
        return 2
    if turns == 0:
        print("trace has no turn_start markers; harness did not record turns", file=sys.stderr)
        return 2
    if unparsed > events:
        print("trace is mostly unparseable", file=sys.stderr)
        return 2
    print(f"trace audit passed: {path} ({turns} turns, {events} events, {results} results)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
