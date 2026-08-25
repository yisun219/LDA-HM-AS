"""Fail-closed programmatic fences."""

from __future__ import annotations

import fnmatch
import hashlib
import json
import subprocess
from dataclasses import dataclass
from pathlib import Path

from .models import Mission
from .trace import audit_trace


@dataclass(frozen=True)
class FenceResult:
    name: str
    passed: bool
    evidence: str
    reward: float = 1.0


def tree_digest(root: Path, excluded: tuple[str, ...] = ()) -> str:
    digest = hashlib.sha256()
    for path in sorted(root.rglob("*")):
        rel = path.relative_to(root).as_posix()
        if any(fnmatch.fnmatch(rel, pattern) for pattern in excluded) or not path.is_file():
            continue
        digest.update(rel.encode())
        digest.update(b"\0")
        digest.update(hashlib.sha256(path.read_bytes()).digest())
    return digest.hexdigest()


def protected_diff(before: dict[str, str], root: Path, protected: tuple[str, ...]) -> FenceResult:
    after = {
        item: hashlib.sha256((root / item).read_bytes()).hexdigest()
        for item in before
        if (root / item).exists()
    }
    changed = [item for item in before if after.get(item) != before[item]]
    deleted = [item for item in before if not (root / item).exists()]
    if changed or deleted:
        return FenceResult(
            "protected_paths", False, json.dumps({"changed": changed, "deleted": deleted})
        )
    return FenceResult("protected_paths", True, "protected path hashes unchanged")


def source_allowlist(
    root: Path, allowed: tuple[str, ...], untracked: tuple[str, ...]
) -> FenceResult:
    proc = subprocess.run(
        ["git", "-C", str(root), "status", "--porcelain", "--untracked-files=all"],
        capture_output=True,
        text=True,
        check=False,
    )
    if proc.returncode:
        return FenceResult("source_allowlist", False, proc.stderr.strip())
    bad = []
    for line in proc.stdout.splitlines():
        rel = line[3:].strip() if len(line) >= 4 else line.strip()
        if rel.startswith('"'):
            rel = rel.strip('"')
        if not any(
            rel == item or rel.startswith(item.rstrip("/") + "/") for item in allowed
        ) and not any(fnmatch.fnmatch(rel, pattern) for pattern in untracked):
            bad.append(rel)
    return FenceResult("source_allowlist", not bad, json.dumps({"out_of_scope": bad}))


def cpu_fence(root: Path, forbidden: tuple[str, ...]) -> FenceResult:
    proc = subprocess.run(
        ["git", "-C", str(root), "diff", "--binary"], capture_output=True, text=True, check=False
    )
    hits = [flag for flag in forbidden if flag in proc.stdout]
    return FenceResult("cpu_policy", not hits, json.dumps({"forbidden_flags": hits}))


def trace_fence(trace: Path, mission: Mission) -> FenceResult:
    findings = audit_trace(
        trace, mission.protected_paths, mission.cpu_policy.forbidden_global_flags
    )
    return FenceResult(
        "trace", not findings, json.dumps([finding.__dict__ for finding in findings])
    )


def run_command_fence(name: str, commands: tuple[tuple[str, ...], ...], runner) -> FenceResult:
    evidence = []
    for argv in commands:
        result = runner(argv)
        evidence.append(
            {
                "argv": argv,
                "returncode": result.returncode,
                "stdout": result.stdout[-2000:],
                "stderr": result.stderr[-2000:],
            }
        )
        if result.returncode != 0:
            return FenceResult(name, False, json.dumps(evidence), 0.0)
    return FenceResult(name, True, json.dumps(evidence))
