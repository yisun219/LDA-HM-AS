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
import os
import re
import sys
import tempfile
import time
import uuid
from pathlib import Path

from .sandbox import E2BSandbox


_TRACE_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]*\.jsonl$")


def _persist_role_traces(sandbox, results_root: Path, run_id: str, current_session: str) -> None:
    """Mirror completed in-sandbox role traces into the durable run directory."""
    if not _TRACE_NAME.fullmatch(f"{run_id}.jsonl"):
        return
    destination = results_root / "runs" / run_id / "raw-traces"
    destination.mkdir(parents=True, exist_ok=True)
    listing = sandbox.run(
        (
            "find",
            "/opt/lda/agent-state/traces",
            "-maxdepth",
            "1",
            "-type",
            "f",
            "-name",
            "*.jsonl",
            "-printf",
            "%f\n",
        ),
        timeout_seconds=60,
    )
    if not listing.ok:
        return
    for name in sorted(set(listing.stdout.splitlines())):
        if not _TRACE_NAME.fullmatch(name):
            continue
        local = destination / name
        if local.is_file() and name != f"{current_session}.jsonl":
            continue
        captured = sandbox.run(
            ("cat", "--", f"/opt/lda/agent-state/traces/{name}"),
            timeout_seconds=120,
        )
        if not captured.ok or not captured.stdout:
            continue
        temporary = local.with_name(f".{local.name}.{os.getpid()}.tmp")
        try:
            temporary.write_text(captured.stdout, encoding="utf-8")
            os.replace(temporary, local)
        finally:
            temporary.unlink(missing_ok=True)


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

    broker_path = str(live.get("broker") or "")
    if broker_path and Path(broker_path).exists():
        from .broker import BrokerClient

        sandbox = BrokerClient(Path(broker_path))
    else:
        # Legacy path for gateways that serve attached clients.
        sandbox = E2BSandbox.attach(str(live["sandbox_id"]))
    remote_tmp = os.getenv("LDA_REMOTE_TMPDIR", "/scratch/lda-hm")
    remote_prompt = f"{remote_tmp}/lda-{args.role}-{uuid.uuid4().hex[:8]}.prompt"
    local_tmp = os.getenv("TMPDIR", "/scratch/lda-hm")
    Path(local_tmp).mkdir(parents=True, exist_ok=True)
    local = Path(tempfile.mkstemp(prefix="lda-hmz-prompt-", dir=local_tmp)[1])
    try:
        local.write_text(prompt, encoding="utf-8")
        sandbox.put(local, remote_prompt)
    finally:
        local.unlink(missing_ok=True)

    effort = {"xhigh": "max"}.get(args.effort, args.effort) or "high"
    environment = [f"LDA_AGENT_THINKING={effort}", f"LDA_TURN_TIMEOUT={os.getenv('LDA_TURN_TIMEOUT', '4200')}"]
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
    # The harness bounds each attempt with LDA_TURN_TIMEOUT and retries once;
    # the relay's deadline must outlive both attempts so the in-sandbox
    # process is always the one that dies first, never the observer.
    turn_timeout = int(os.getenv("LDA_TURN_TIMEOUT", "4200"))
    result = sandbox.run(command, timeout_seconds=2 * turn_timeout + 600)
    results_root = os.getenv("LDA_RESULTS_ROOT", "")
    run_id = os.getenv("LDA_RUN_ID", "")
    if results_root and run_id:
        try:
            _persist_role_traces(sandbox, Path(results_root), run_id, args.session)
        except Exception as error:
            print(f"relay: could not persist role traces: {error}", file=sys.stderr)
    print(f"LDA-SESSION: {args.session}", file=sys.stderr)
    if result.stderr:
        sys.stderr.write(result.stderr[-4000:])
    sys.stdout.write(result.stdout)
    return result.exit_code


if __name__ == "__main__":
    raise SystemExit(main())
