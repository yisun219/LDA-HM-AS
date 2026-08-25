from __future__ import annotations

import json
import re
from pathlib import Path

from pydantic import BaseModel, ConfigDict


class AntiCheatFinding(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    rule: str
    evidence: str


RULES = {
    "benchmark_modified": re.compile(r"(?:rm|mv|sed|perl|truncate|>|apply_patch).*?(?:benchmark|workload|test)", re.I),
    "affinity_changed": re.compile(r"(?:taskset|numactl).*?(?:-[cp]|--physcpubind|--cpunodebind)", re.I),
    "undeclared_preload": re.compile(r"LD_PRELOAD\s*=", re.I),
    "march_native": re.compile(r"-march=native\b"),
    "network_binary": re.compile(r"(?:curl|wget).*?(?:\.so|\.a|\.deb|binary|release)", re.I),
    "hidden_samples": re.compile(r"(?:head|tail|sort).*?(?:best|min|fastest)|drop.*?sample", re.I),
    "system_library_write": re.compile(r"(?:cp|mv|install).*?/(?:usr/)?lib(?:32|64)?/", re.I),
}


def scan_trace(path: Path) -> list[AntiCheatFinding]:
    findings: list[AntiCheatFinding] = []
    for line_number, raw in enumerate(path.read_text(encoding="utf-8", errors="replace").splitlines(), 1):
        try:
            event = json.loads(raw)
            searchable = json.dumps(event, sort_keys=True)
        except ValueError:
            searchable = raw
        for rule, pattern in RULES.items():
            if pattern.search(searchable):
                findings.append(AntiCheatFinding(rule=rule, evidence=f"line {line_number}: {searchable[:500]}"))
    return findings
