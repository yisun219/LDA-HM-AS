#!/usr/bin/env python3
"""Collect E2B sandboxes no live LDA run still owns.

A run releases its own sandbox on every exit path it can observe (see
`driver.py`), but a SIGKILL'd or OOM-killed driver cannot. Those sandboxes then
hold their disk image on the shared E2B host until the re-armed TTL expires,
which is what makes our footprint look enormous to everyone else on the box.

Ownership is read from each run workspace's `.lda-hm/live-sandbox.json`, which
the flow writes when it adopts a sandbox. A sandbox is reaped when no workspace
claims it AND no driver process is alive for that workspace.

    reap-sandboxes.py --list              # show what would be reaped
    reap-sandboxes.py --reap              # actually kill them
    reap-sandboxes.py --reap --older 900  # only ones started >15min ago
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

RUNS_ROOT = Path(
    os.getenv("LDA_RUNS_ROOT", "/fact_data/yisun/Linux-Development-Agent-Runs/runs")
)
WORKSPACE_ROOTS = [
    Path(p)
    for p in os.getenv(
        "LDA_WORKSPACE_ROOTS", "/fact_data/yisun/lda-workspaces"
    ).split(":")
    if p
]


def api(path: str, method: str = "GET"):
    base = os.environ["E2B_API_URL"].rstrip("/")
    request = urllib.request.Request(
        f"{base}{path}",
        method=method,
        headers={"X-API-KEY": os.environ["E2B_API_KEY"]},
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        body = response.read()
        return json.loads(body) if body else None


def claimed_sandbox_ids() -> dict[str, Path]:
    """sandbox_id -> workspace, for every workspace that claims one."""
    claims: dict[str, Path] = {}
    for root in [*WORKSPACE_ROOTS, RUNS_ROOT]:
        if not root.is_dir():
            continue
        for live in root.glob("*/.lda-hm/live-sandbox.json"):
            try:
                payload = json.loads(live.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue
            sandbox_id = payload.get("sandbox_id")
            if sandbox_id:
                claims[str(sandbox_id)] = live.parent.parent
    return claims


def workspace_has_live_driver(workspace: Path) -> bool:
    """True if some process still holds this workspace open."""
    try:
        found = subprocess.run(
            ["pgrep", "-af", "lda_hm|lda run|flows/lda"],
            capture_output=True,
            text=True,
            timeout=20,
        ).stdout
    except (OSError, subprocess.SubprocessError):
        return True  # cannot tell; never reap on a guess
    return workspace.name in found or str(workspace) in found


def age_seconds(sandbox: dict) -> float:
    started = sandbox.get("startedAt") or sandbox.get("started_at")
    if not started:
        return 0.0
    try:
        stamp = datetime.fromisoformat(str(started).replace("Z", "+00:00"))
    except ValueError:
        return 0.0
    return (datetime.now(timezone.utc) - stamp).total_seconds()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--reap", action="store_true", help="kill the orphans")
    parser.add_argument("--list", action="store_true", help="report only")
    parser.add_argument(
        "--older",
        type=float,
        default=600.0,
        help="only consider sandboxes older than this many seconds",
    )
    args = parser.parse_args()
    if not (args.reap or args.list):
        args.list = True

    try:
        sandboxes = api("/sandboxes") or []
    except (urllib.error.URLError, OSError, KeyError) as error:
        print(f"cannot list sandboxes: {error}", file=sys.stderr)
        return 2

    claims = claimed_sandbox_ids()
    orphans, kept = [], []
    for sandbox in sandboxes:
        sandbox_id = str(
            sandbox.get("sandboxID") or sandbox.get("sandbox_id") or ""
        )
        if not sandbox_id:
            continue
        age = age_seconds(sandbox)
        owner = claims.get(sandbox_id)
        if owner is not None and workspace_has_live_driver(owner):
            kept.append((sandbox_id, f"owned by live run {owner.name}"))
        elif age < args.older:
            kept.append((sandbox_id, f"too young ({int(age)}s)"))
        else:
            why = "unclaimed" if owner is None else f"owner {owner.name} is dead"
            orphans.append((sandbox_id, age, why))

    print(f"live sandboxes: {len(sandboxes)}  orphans: {len(orphans)}")
    for sandbox_id, reason in kept:
        print(f"  keep  {sandbox_id[:24]}  {reason}")
    for sandbox_id, age, why in orphans:
        print(f"  ORPHAN {sandbox_id[:24]}  age={int(age)}s  {why}")

    if not args.reap:
        return 0
    failed = 0
    for sandbox_id, _age, _why in orphans:
        try:
            api(f"/sandboxes/{sandbox_id}", method="DELETE")
            print(f"  reaped {sandbox_id[:24]}")
        except (urllib.error.URLError, OSError) as error:
            failed += 1
            print(f"  FAILED {sandbox_id[:24]}: {error}", file=sys.stderr)
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
