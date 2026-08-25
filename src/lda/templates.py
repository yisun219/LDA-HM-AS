from __future__ import annotations

import json
from pathlib import Path


TEMPLATES = {
    "lda-controller": {"roles": ["Argus Supervisor", "Humanize Runtime", "Mission Scheduler", "Policy Engine", "AgentFactory", "E2B Client", "Tool Gateway", "World State", "Outcome Ledger", "Capability Registry", "State Store", "Artifact Store", "Secret Redactor"]},
    "lda-agent-runtime": {"roles": ["Codex SDK/CLI", "Agent Runner", "JSON Schema", "MCP Client", "Role Prompt", "Intel Performance Skills"]},
    "lda-base": {"tools": ["Ubuntu 26.04", "GCC", "Clang", "LLD", "CMake", "Ninja", "Meson", "autotools", "debhelper", "perf", "strace", "valgrind", "bpftrace", "numactl", "abi-compliance-checker", "Benchmark Harness"]},
    "lda-judge": {"checks": ["ABI/API/FFI Fence", "self test", "reverse dependency", "benchmark", "anti-cheat", "package install/rollback"], "llm": False},
    "lda-e2e": {"tools": ["Chrome", "Playwright", "Web server", "GUI", "system workload"]},
}


def build_templates(root: str | Path, names: list[str] | None = None) -> list[str]:
    root = Path(root)
    template_root = root / "e2b_templates"
    built: list[str] = []
    for name in names or list(TEMPLATES):
        if name not in TEMPLATES:
            raise ValueError(f"unknown template: {name}")
        path = template_root / name
        path.mkdir(parents=True, exist_ok=True)
        (path / "manifest.json").write_text(json.dumps({"name": name, "version": "1", **TEMPLATES[name]}, indent=2) + "\n", encoding="utf-8")
        built.append(name)
    return built

