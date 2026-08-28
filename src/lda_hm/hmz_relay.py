"""Relay one hmz agent turn into the card's live E2B sandbox.

Run by the hmz runtime as a turn command (`python -m lda_hm.hmz_relay`),
with the prompt on stdin. The relay attaches to the sandbox the flow
recorded in <workspace>/.lda-hm/live-sandbox.json, uploads the prompt,
executes the in-sandbox LDA harness for the given role and session, and
prints the harness reply on stdout. A nonzero harness exit propagates, so
hmz reads a failed turn as `Failed` exactly like any other backend.
"""
from __future__ import annotations

import argparse
import json
import sys
import tempfile
import time
import uuid
from pathlib import Path

from .sandbox import E2BSandbox


def main() -> int:
    parser = argparse.ArgumentParser(prog="lda-hmz-relay")
    parser.add_argument("--cwd", required=True)
    parser.add_argument("--role", required=True)
    parser.add_argument("--session", required=True)
    parser.add_argument("--model", default="")
    parser.add_argument("--effort", default="high")
    args = parser.parse_args()

    prompt = sys.stdin.read()
    if not prompt.strip():
        print("relay: empty prompt", file=sys.stderr)
        return 64

    live_file = Path(args.cwd) / ".lda-hm" / "live-sandbox.json"
    deadline = time.monotonic() + 120
    live = None
    while time.monotonic() < deadline:
        try:
            live = json.loads(live_file.read_text(encoding="utf-8"))
            break
        except (OSError, json.JSONDecodeError):
            time.sleep(3)
    if not isinstance(live, dict) or not live.get("sandbox_id"):
        print(f"relay: no live sandbox recorded at {live_file}", file=sys.stderr)
        return 69

    sandbox = E2BSandbox.attach(str(live["sandbox_id"]))
    remote_prompt = f"/tmp/lda-{args.role}-{uuid.uuid4().hex[:8]}.prompt"
    local = Path(tempfile.mkstemp(prefix="lda-hmz-prompt-")[1])
    try:
        local.write_text(prompt, encoding="utf-8")
        sandbox.put(local, remote_prompt)
    finally:
        local.unlink(missing_ok=True)

    effort = {"xhigh": "max"}.get(args.effort, args.effort) or "high"
    environment = [f"LDA_AGENT_THINKING={effort}"]
    if args.model:
        environment.append(f"LDA_AGENT_MODEL_{args.role.upper()}={args.model}")
    command = (
        "env",
        *environment,
        "/opt/lda/harness/lda-agent-harness.sh",
        "--prompt-file",
        remote_prompt,
        "--role",
        args.role,
        "--session",
        args.session,
    )
    result = sandbox.run(command, timeout_seconds=int(3600 * 1.5))
    print(f"LDA-SESSION: {args.session}", file=sys.stderr)
    if result.stderr:
        sys.stderr.write(result.stderr[-4000:])
    sys.stdout.write(result.stdout)
    return result.exit_code


if __name__ == "__main__":
    raise SystemExit(main())
