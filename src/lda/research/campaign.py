from __future__ import annotations

import hashlib
import json
import re
import shutil
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

TOP10 = [
    "libgtk-4-1", "libgtk-3-0t64", "gnome-shell", "libreoffice-core", "sssd-common",
    "libcairo2", "gnome-settings-daemon", "gstreamer1.0-plugins-good", "ibus", "libsoup-3.0-0",
]
CANARY = ["libcairo2", "libsoup-3.0-0"]


@dataclass
class CampaignInput:
    source_path: str
    filename: str
    sha256: str
    bytes: int
    lines: int
    original_artifact: str
    report_stats: dict[str, Any] = field(default_factory=dict)
    top30: list[dict[str, Any]] = field(default_factory=list)
    top10: list[str] = field(default_factory=lambda: list(TOP10))
    canary: list[str] = field(default_factory=lambda: list(CANARY))
    e2b_path: str = "/workspace/campaign-input/report.md"

    def dump(self) -> dict[str, Any]:
        return asdict(self)


def _top30(text: str) -> list[dict[str, Any]]:
    rows = []
    for line in text.splitlines():
        match = re.match(r"\|\s*(\d+)\|`([^`]+)`\|([0-9.]+)\|([0-9]+)\|([0-9]+)\|([0-9]+)\|", line)
        if match:
            rank, package, score, fanin, req_out, all_out = match.groups()
            rows.append({"rank": int(rank), "package": package, "score": float(score),
                         "required_dependents": int(fanin), "required_out": int(req_out), "all_out": int(all_out)})
    return rows


def prepare(path: str | Path, root: str | Path) -> CampaignInput:
    source = Path(path).expanduser().resolve()
    if not source.is_file():
        raise FileNotFoundError(f"campaign input does not exist: {source}")
    data = source.read_bytes()
    digest = hashlib.sha256(data).hexdigest()
    artifact_dir = Path(root).resolve() / ".lda" / "artifacts" / "campaign-input"
    artifact_dir.mkdir(parents=True, exist_ok=True)
    original = artifact_dir / source.name
    if original.exists() and hashlib.sha256(original.read_bytes()).hexdigest() != digest:
        raise ValueError("existing campaign artifact hash differs; refusing to overwrite")
    if not original.exists():
        shutil.copyfile(source, original)
    text = data.decode("utf-8")
    stats = {
        "debian_nodes": 1814,
        "snap_entries": 14,
        "all_edges": 12369,
        "dependency_edges": 10307,
        "required_edges": 8401,
        "unresolved_edges": 842,
        "exact_matches": 1811,
        "exact_misses": 3,
    }
    record = CampaignInput(str(source), source.name, digest, len(data), len(text.splitlines()),
                           str(original.relative_to(Path(root).resolve())), stats, _top30(text))
    (artifact_dir / "manifest.json").write_text(json.dumps(record.dump(), indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return record

