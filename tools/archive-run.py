#!/usr/bin/env python3
"""Archive one run's evidence and agent traces into this repository.

    tools/archive-run.py <results-root>/runs/<run-id> [--repo-dir runs]

Copies the durable evidence (task card, sealed plan, per-round summaries and
supervision decisions, benchmark and certification summaries, the candidate
patch, finalize and methodology reports, the journal) and every agent trace
(gzip-compressed; the builder, planner, analyst, reviewer and supervisor
stream-json files) into runs/<run-id>/ so the repository carries the whole
record of how a result was reached, not just the number.

Secrets never enter the repository: every value found in the operator's
private gateway and sandbox configuration files is replaced by
"<redacted>" in the copied text, and the archive is refused if any such
value survives the scrub.
"""
from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import os
import shutil
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
EVIDENCE = (
    "task-card.json", "task.md", "run.json", "state.json", "journal.jsonl", "baseline.json",
    "idea.md", "plan.md", "plan.sha256", "goal-tracker.md", "candidate.patch", "candidate-log.txt",
    "benchmark-summary.json", "certification-summary.json", "fence-selfcheck.json",
    "code-review.json", "finalize-summary.md", "methodology-report.md", "speedup-report.md",
    "bitlesson.md", "builder-trace.json", "integrity-manifest.sha256",
)
EVIDENCE_DIRS = ("rounds", "planning", "benchmarks", "packages")
SECRET_FILES = (
    Path.home() / ".config/lda/factlab-claude.env",
    Path.home() / ".config/lda/codex.env",
    Path.home() / ".config/lda/claude.env",
    Path.home() / ".config/lda-hm/e2b.env",
)


def secret_values() -> list[bytes]:
    values: list[bytes] = []
    for path in SECRET_FILES:
        try:
            for line in path.read_text(encoding="utf-8").splitlines():
                line = line.strip().removeprefix("export ").strip()
                if "=" not in line or line.startswith("#"):
                    continue
                value = line.split("=", 1)[1].strip().strip('"').strip("'")
                if len(value) >= 12 and not value.startswith("$") and not value.startswith("http"):
                    values.append(value.encode())
        except OSError:
            continue
    return values


def scrub(data: bytes, secrets: list[bytes]) -> bytes:
    for value in secrets:
        data = data.replace(value, b"<redacted>")
    return data


def copy_file(src: Path, dst: Path, secrets: list[bytes], compress: bool) -> str:
    dst.parent.mkdir(parents=True, exist_ok=True)
    data = scrub(src.read_bytes(), secrets)
    for value in secrets:
        if value in data:
            raise SystemExit(f"refusing to archive {src}: a secret survived the scrub")
    if compress:
        dst = dst.with_name(dst.name + ".gz")
        with gzip.open(dst, "wb", compresslevel=9) as stream:
            stream.write(data)
    else:
        dst.write_bytes(data)
    return f"{hashlib.sha256(data).hexdigest()}  {dst.relative_to(REPO)}"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("run_dir", type=Path)
    parser.add_argument("--repo-dir", default="runs")
    args = parser.parse_args()
    run_dir = args.run_dir.resolve()
    if not (run_dir / "state.json").is_file():
        raise SystemExit(f"{run_dir} is not a run directory")
    target = REPO / args.repo_dir / run_dir.name
    if target.exists():
        shutil.rmtree(target)
    secrets = secret_values()
    manifest: list[str] = []
    for name in EVIDENCE:
        src = run_dir / name
        if src.is_file():
            manifest.append(copy_file(src, target / name, secrets, compress=False))
    for directory in EVIDENCE_DIRS:
        src_dir = run_dir / directory
        if src_dir.is_dir():
            for src in sorted(p for p in src_dir.rglob("*") if p.is_file()):
                rel = src.relative_to(run_dir)
                manifest.append(copy_file(src, target / rel, secrets, compress=src.suffix == ".deb" and False))
    traces = run_dir / "raw-traces"
    if traces.is_dir():
        for src in sorted(traces.glob("*.jsonl")):
            manifest.append(copy_file(src, target / "raw-traces" / src.name, secrets, compress=True))
    (target / "ARCHIVE-SHA256SUMS").write_text("\n".join(manifest) + "\n", encoding="utf-8")
    state = json.loads((run_dir / "state.json").read_text(encoding="utf-8"))
    print(f"archived {run_dir.name}: phase={state.get('phase')} files={len(manifest)} -> {target.relative_to(REPO)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
