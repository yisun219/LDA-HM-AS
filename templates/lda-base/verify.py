"""Fail-closed verification commands for lda-base."""

from __future__ import annotations

import os
import shutil
import subprocess

REQUIRED = (
    "readelf",
    "objdump",
    "abidiff",
    "abi-dumper",
    "abi-compliance-checker",
    "perf",
    "fio",
    "convert",
    "chromium",
    "node",
    "python3",
    "git",
    "hmz",
    "lda-flow",
    "codex",
)


def main() -> int:
    if os.getenv("E2B_API_KEY"):
        print("E2B_API_KEY is present but never printed")
    version = subprocess.check_output(
        ["bash", "-lc", ". /etc/os-release; printf '%s' \"$VERSION_ID\""], text=True
    ).strip()
    if version != "26.04":
        raise SystemExit(f"wrong Ubuntu VERSION_ID: {version}")
    missing = [name for name in REQUIRED if shutil.which(name) is None]
    if missing:
        raise SystemExit("missing tools: " + ", ".join(missing))
    skills = [
        "/opt/intel-performance-skills/skills/linux-perf/SKILL.md",
        "/opt/intel-performance-skills/skills/performance-patterns/SKILL.md",
        "/opt/intel-performance-skills/skills/phoronix-test-suite/SKILL.md",
    ]
    missing_skills = [path for path in skills if not os.path.isfile(path)]
    if missing_skills:
        raise SystemExit("missing Intel skills: " + ", ".join(missing_skills))
    model = subprocess.check_output(
        ["grep", "-m1", "model name", "/proc/cpuinfo"], text=True
    ).strip()
    print(f"Ubuntu VERSION_ID={version}; cpu={model}; required_tools=ok; intel_skills=ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
