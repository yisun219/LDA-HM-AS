from __future__ import annotations

import hashlib
import os
import tempfile
from pathlib import Path


class ArtifactStore:
    PREFIX = "sha256:"

    def __init__(self, root: str | Path):
        self.root = Path(root).resolve() / ".lda" / "artifacts"
        self.objects = self.root / "sha256"
        self.objects.mkdir(parents=True, exist_ok=True)

    def _path(self, digest: str) -> Path:
        if len(digest) != 64 or any(char not in "0123456789abcdef" for char in digest):
            raise ValueError("invalid artifact sha256")
        return self.objects / digest[:2] / digest

    def put(self, name: str, content: bytes) -> str:
        digest = hashlib.sha256(content).hexdigest()
        path = self._path(digest)
        path.parent.mkdir(parents=True, exist_ok=True)
        if path.exists():
            if hashlib.sha256(path.read_bytes()).hexdigest() != digest:
                raise RuntimeError("content-addressed artifact is corrupted")
            return self.PREFIX + digest
        fd, temporary = tempfile.mkstemp(prefix="artifact.", dir=path.parent)
        try:
            with os.fdopen(fd, "wb") as fh:
                fh.write(content)
                fh.flush()
                os.fsync(fh.fileno())
            os.replace(temporary, path)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)
        return self.PREFIX + digest

    def get(self, ref: str) -> bytes:
        if ref.startswith(self.PREFIX):
            digest = ref[len(self.PREFIX):]
            content = self._path(digest).read_bytes()
            if hashlib.sha256(content).hexdigest() != digest:
                raise RuntimeError("content-addressed artifact hash mismatch")
            return content
        # Existing runs used absolute paths. Retain read compatibility while
        # all newly written refs use immutable sha256 identifiers.
        return Path(ref).read_bytes()

    def path(self, ref: str) -> Path:
        if not ref.startswith(self.PREFIX):
            return Path(ref)
        return self._path(ref[len(self.PREFIX):])
