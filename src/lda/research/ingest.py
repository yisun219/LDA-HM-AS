from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from lda.models import new_id, utc_now


def ingest(paths: list[str | Path], root: str | Path) -> dict[str, Any]:
    files: list[dict[str, Any]] = []
    for raw in paths:
        path = Path(raw)
        candidates = sorted(path.rglob("*") if path.is_dir() else [path])
        for item in candidates:
            if item.is_file():
                data = item.read_bytes()
                files.append({"path": str(item), "sha256": hashlib.sha256(data).hexdigest(), "bytes": len(data)})
    snapshot = {"snapshot_id": new_id("research"), "created_at": utc_now(), "sources": files,
                "confidence": 1.0 if files else 0.0, "validated": bool(files)}
    target = Path(root) / ".lda" / "research"
    target.mkdir(parents=True, exist_ok=True)
    (target / f"{snapshot['snapshot_id']}.json").write_text(json.dumps(snapshot, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return snapshot

