from __future__ import annotations

import hashlib
from pathlib import Path


class ArtifactStore:
    def __init__(self, root: str | Path):
        self.root = Path(root).resolve() / ".lda" / "artifacts"
        self.root.mkdir(parents=True, exist_ok=True)

    def put(self, name: str, content: bytes) -> str:
        digest = hashlib.sha256(content).hexdigest()
        path = self.root / f"{digest}-{Path(name).name}"
        path.write_bytes(content)
        return str(path)

    def get(self, ref: str) -> bytes:
        return Path(ref).read_bytes()

