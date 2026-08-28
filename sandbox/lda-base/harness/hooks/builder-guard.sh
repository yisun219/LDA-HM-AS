#!/usr/bin/env bash
# In-turn mechanical enforcement for the Builder session, in the tradition of
# Humanize's loop-bash-validator / loop-edit-validator: the agent runtime
# consults this hook BEFORE executing each tool call, and a block here stops
# the call itself - tampering is prevented during the turn, not just detected
# after it. Defense-in-depth: root-sealing, the integrity manifest, the patch
# scan, and the trace audit all remain in force behind this.
#
# Contract (Claude Code PreToolUse hook): JSON on stdin; exit 0 allows,
# exit 2 blocks with stderr shown to the agent as the reason.
set -uo pipefail

payload_file="$(mktemp)"
trap 'rm -f "$payload_file"' EXIT
cat >"$payload_file"

decision="$(python3 - "$payload_file" <<'PY'
import json
import re
import sys

try:
    with open(sys.argv[1], encoding="utf-8") as stream:
        event = json.load(stream)
except (OSError, json.JSONDecodeError, IndexError):
    print("allow")
    raise SystemExit(0)

tool = event.get("tool_name", "")
arguments = event.get("tool_input") or {}

PROTECTED = re.compile(
    r"/opt/lda/(control|review|baseline|harness|fixtures|skills|agent-state/traces)\b"
)

def block(reason: str) -> None:
    print("block:" + reason)
    raise SystemExit(0)

if tool in {"Write", "Edit", "NotebookEdit"}:
    path = str(arguments.get("file_path", ""))
    if PROTECTED.search(path):
        block(f"{tool} to protected path {path}: control, review, baseline, "
              "harness, fixtures, skills, and traces are immutable evidence")

if tool == "Bash":
    command = str(arguments.get("command", ""))
    # Writing into protected trees through the shell, however spelled.
    write_forms = (
        r"(?:>|>>|\btee\b|\bmv\b|\bcp\b|\brm\b|\bln\b|\btruncate\b|\bdd\b[^|]*\bof=|"
        r"\bsed\s+-i|\bperl\s+-p?i|\bchmod\b|\bchown\b|\bchattr\b|\binstall\b)"
    )
    if re.search(write_forms, command) and PROTECTED.search(command):
        block("shell write/permission change touching a protected path: "
              "control, review, baseline, harness, fixtures, skills, and "
              "traces are immutable evidence")
    if re.search(r"\bgit\s+push\b", command):
        block("git push is not part of a sandboxed optimization round")
    if re.search(r"\bpkill\b.*(claude|codex|(^|\s)pi\b)|\bkill\b.*-9", command) and \
       re.search(r"claude|codex|(^|\s)pi\b", command):
        block("killing agent processes is the Supervisor's authority, not the Builder's")
    if re.search(r"holdout", command, re.IGNORECASE):
        block("the holdout fixture set must stay invisible to the Builder")
    if re.search(r"\bsysctl\b|\bmount\b|\bumount\b", command):
        block("host/kernel state changes are outside a package optimization round")

print("allow")
PY
)"

case "$decision" in
  allow)
    exit 0
    ;;
  block:*)
    printf '%s\n' "BLOCKED BY BUILDER GUARD: ${decision#block:}" >&2
    exit 2
    ;;
  *)
    # A guard that cannot parse must not silently wave things through
    # dangerous paths; log and allow (the sealed layers still hold).
    exit 0
    ;;
esac
