#!/usr/bin/env python3
"""Fan a job list out over disposable E2B sandboxes, one sandbox per job.

Usage:
    uv run --with e2b==2.40.0 python tools/e2b/fanout.py jobs.json \
        [--out out] [--concurrency 8] [--template lda-ubuntu2604] \
        [--timeout 1800] [--cmd-timeout 1800] [--retries 2] [--dry-run]

Job list format (JSON array):

    [
      {
        "name": "xz-utils",                  # required, becomes out/<name>/
        "template": "lda-ubuntu2604",        # optional per-job override
        "envs": {"DEB_BUILD_OPTIONS": "..."},# optional, sandbox env
        "upload": [{"local": "src.tar",      # optional, host -> sandbox
                    "remote": "/work/src.tar"}],
        "setup_cmds": ["apt-get update"],    # run first, failure aborts the job
        "run_cmds": ["dpkg-buildpackage -b"],# the actual work
        "fetch": ["/work/out/*.deb"]         # sandbox -> out/<name>/
      }
    ]

Guarantees that matter for evidence:
  * every `fetch` path is pulled out BEFORE the sandbox is killed;
  * each fetched file is sha256'd inside the sandbox and again on the host,
    and the pair is recorded, so a truncated transfer cannot pass silently;
  * the sandbox is killed in a `finally`, so a crashed job still gets torn
    down rather than idling out on the host;
  * retries stop as soon as two attempts fail the same way.

Credentials come from the environment only (see e2b_common.py). Nothing in
this file or in jobs.json should ever contain a key.
"""

from __future__ import annotations

import argparse
import fnmatch
import hashlib
import json
import os
import posixpath
import sys
import time
import traceback
from concurrent.futures import ThreadPoolExecutor
from typing import Any

from e2b import Sandbox

from e2b_common import configure_shared_gateway, default_template, require_env

TAIL = 4000  # bytes of stdout/stderr kept per step in the summary


def _tail(s: str, n: int = TAIL) -> str:
    s = s or ""
    return s if len(s) <= n else "...[truncated]...\n" + s[-n:]


def _sha256_bytes(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def expand_fetch(sbx: Sandbox, pattern: str) -> list[str]:
    """Resolve a fetch entry to concrete sandbox paths.

    A literal path is returned as-is. A glob is expanded by listing its
    directory inside the sandbox -- the SDK filesystem API has no glob."""
    if not any(c in pattern for c in "*?["):
        return [pattern]
    d = posixpath.dirname(pattern) or "/"
    base = posixpath.basename(pattern)
    try:
        entries = sbx.files.list(d)
    except Exception:  # noqa: BLE001 - missing dir means nothing matched
        return []
    return [
        posixpath.join(d, e.name)
        for e in entries
        if fnmatch.fnmatch(e.name, base) and getattr(e, "type", None) != "dir"
    ]


def run_job(job: dict, args: argparse.Namespace) -> dict:
    name = job["name"]
    template = job.get("template") or args.template
    rec: dict[str, Any] = {
        "name": name,
        "template": template,
        "ok": False,
        "attempts": 0,
        "steps": [],
        "fetched": [],
        "errors": [],
    }
    seen_failures: list[str] = []

    for attempt in range(1, args.retries + 1):
        rec["attempts"] = attempt
        rec["steps"] = []
        rec["fetched"] = []
        sbx = None
        t_job = time.time()
        try:
            t0 = time.time()
            sbx = Sandbox.create(
                template=template,
                timeout=args.timeout,
                envs=job.get("envs") or None,
                metadata={"lda_job": name},
            )
            rec["create_s"] = round(time.time() - t0, 2)
            rec["sandbox_id"] = sbx.sandbox_id

            for up in job.get("upload") or []:
                with open(up["local"], "rb") as fh:
                    data = fh.read()
                sbx.files.write(up["remote"], data)
                rec["steps"].append(
                    {
                        "cmd": f"<upload {up['local']} -> {up['remote']}>",
                        "exit_code": 0,
                        "duration_s": 0.0,
                        "bytes": len(data),
                        "sha256_host": _sha256_bytes(data),
                    }
                )

            failed = False
            for phase in ("setup_cmds", "run_cmds"):
                for cmd in job.get(phase) or []:
                    t1 = time.time()
                    r = sbx.commands.run(
                        cmd,
                        timeout=args.cmd_timeout,
                        cwd=job.get("cwd"),
                        envs=job.get("envs") or None,
                    )
                    rec["steps"].append(
                        {
                            "phase": phase,
                            "cmd": cmd,
                            "exit_code": r.exit_code,
                            "duration_s": round(time.time() - t1, 2),
                            "stdout": _tail(r.stdout),
                            "stderr": _tail(r.stderr),
                        }
                    )
                    if r.exit_code != 0:
                        failed = True
                        rec["errors"].append(
                            f"{phase} exit {r.exit_code}: {cmd}"
                        )
                        break
                if failed:
                    break

            # Evidence out before teardown -- always, even on failure, because
            # a failed build's logs are exactly what we need to read.
            outdir = os.path.join(args.out, name)
            os.makedirs(outdir, exist_ok=True)
            for pattern in job.get("fetch") or []:
                paths = expand_fetch(sbx, pattern)
                if not paths:
                    rec["fetched"].append({"pattern": pattern, "matched": 0})
                    continue
                for p in paths:
                    ent: dict[str, Any] = {"remote": p}
                    try:
                        h = sbx.commands.run(
                            f"sha256sum {json.dumps(p)}", timeout=120
                        )
                        if h.exit_code == 0:
                            ent["sha256_sandbox"] = h.stdout.split()[0]
                        data = sbx.files.read(p, format="bytes")
                        local = os.path.join(outdir, posixpath.basename(p))
                        with open(local, "wb") as fh:
                            fh.write(data)
                        ent.update(
                            local=local,
                            bytes=len(data),
                            sha256_host=_sha256_bytes(data),
                        )
                        ent["sha256_match"] = (
                            ent.get("sha256_sandbox") == ent["sha256_host"]
                        )
                    except Exception as exc:  # noqa: BLE001
                        ent["error"] = f"{type(exc).__name__}: {exc}"
                    rec["fetched"].append(ent)

            bad = [f for f in rec["fetched"] if f.get("sha256_match") is False]
            if bad:
                rec["errors"].append(f"sha256 mismatch on {len(bad)} file(s)")
            rec["ok"] = not failed and not bad
            rec["total_s"] = round(time.time() - t_job, 2)
            if rec["ok"]:
                return rec
            sig = rec["errors"][-1] if rec["errors"] else "unknown"
        except Exception as exc:  # noqa: BLE001 - one bad job must not stop the fleet
            sig = type(exc).__name__
            rec["errors"].append(f"{sig}: {exc}")
            rec["traceback"] = traceback.format_exc()[-2000:]
            rec["total_s"] = round(time.time() - t_job, 2)
        finally:
            if sbx is not None:
                try:
                    sbx.kill()
                    rec["killed"] = True
                except Exception as exc:  # noqa: BLE001
                    rec["errors"].append(f"kill: {type(exc).__name__}: {exc}")

        # Retry discipline: the same cause twice is a wall, not a flake.
        head = sig.split(":")[0]
        if head in seen_failures:
            rec["errors"].append(f"same failure twice ({head}) -- not retrying")
            break
        seen_failures.append(head)
        if attempt < args.retries:
            time.sleep(3.0)

    return rec


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("jobs", help="path to jobs JSON")
    ap.add_argument("--out", default="out")
    ap.add_argument("--concurrency", type=int, default=8)
    ap.add_argument("--template", default=None)
    ap.add_argument("--timeout", type=int, default=1800,
                    help="sandbox lifetime seconds")
    ap.add_argument("--cmd-timeout", type=int, default=1800,
                    help="per-command seconds (SDK default is only 60)")
    ap.add_argument("--retries", type=int, default=2)
    ap.add_argument("--summary", default=None, help="write summary JSON here")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    with open(args.jobs) as fh:
        jobs = json.load(fh)
    if not isinstance(jobs, list) or not jobs:
        raise SystemExit("jobs file must be a non-empty JSON array")
    names = [j["name"] for j in jobs]
    if len(set(names)) != len(names):
        raise SystemExit("job names must be unique (they become out/ dirs)")

    args.template = args.template or default_template()

    if args.dry_run:
        print(f"[dry-run] template={args.template} concurrency={args.concurrency} "
              f"out={args.out} cmd_timeout={args.cmd_timeout}s")
        for j in jobs:
            print(f"\n[dry-run] job {j['name']} (template "
                  f"{j.get('template') or args.template})")
            for up in j.get("upload") or []:
                ok = "OK" if os.path.exists(up["local"]) else "MISSING"
                print(f"    upload {up['local']} -> {up['remote']}  [{ok}]")
            for phase in ("setup_cmds", "run_cmds"):
                for c in j.get(phase) or []:
                    print(f"    {phase}: {c}")
            for f in j.get("fetch") or []:
                print(f"    fetch: {f} -> {os.path.join(args.out, j['name'])}/")
        return 0

    require_env("E2B_API_KEY", "E2B_API_URL")
    configure_shared_gateway()
    os.makedirs(args.out, exist_ok=True)

    t0 = time.time()
    width = min(args.concurrency, len(jobs))
    print(f"fanout: {len(jobs)} job(s), concurrency {width}, "
          f"template {args.template}", flush=True)
    with ThreadPoolExecutor(max_workers=width) as ex:
        recs = list(ex.map(lambda j: run_job(j, args), jobs))
    wall = round(time.time() - t0, 2)

    print(f"\n{'job':<28} {'ok':<4} {'try':<4} {'create':>7} {'total':>8} fetched")
    for r in recs:
        got = sum(1 for f in r["fetched"] if f.get("local"))
        print(f"{r['name']:<28} {str(r['ok']):<4} {r['attempts']:<4} "
              f"{r.get('create_s', '-'):>7} {r.get('total_s', '-'):>8} {got}")
        for e in r["errors"]:
            print(f"    ! {e}")
    n_ok = sum(1 for r in recs if r["ok"])
    print(f"\n{n_ok}/{len(recs)} ok in {wall}s wall")

    summary = {
        "template": args.template,
        "concurrency": width,
        "wall_s": wall,
        "ok": n_ok,
        "total": len(recs),
        "jobs": recs,
    }
    path = args.summary or os.path.join(args.out, "summary.json")
    with open(path, "w") as fh:
        json.dump(summary, fh, indent=2)
    print(f"summary -> {path}")
    return 0 if n_ok == len(recs) else 1


if __name__ == "__main__":
    sys.exit(main())
