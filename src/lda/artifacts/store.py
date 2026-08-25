from __future__ import annotations

import json
import os
from hashlib import sha256
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import Any

from pydantic import BaseModel


class ArtifactStore:
    """Content-addressed immutable artifacts with mutable named references."""

    def __init__(self, root: Path) -> None:
        self.root = root.resolve()
        self.objects = self.root / "objects"
        self.refs = self.root / "refs"
        self.objects.mkdir(parents=True, exist_ok=True)
        self.refs.mkdir(parents=True, exist_ok=True)

    def put_bytes(self, content: bytes) -> str:
        digest = sha256(content).hexdigest()
        target = self.objects / digest[:2] / digest[2:]
        if target.exists():
            if target.read_bytes() != content:
                raise RuntimeError("artifact hash collision")
            return digest
        target.parent.mkdir(parents=True, exist_ok=True)
        with NamedTemporaryFile(dir=target.parent, delete=False) as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
            temporary = Path(stream.name)
        temporary.chmod(0o444)
        temporary.replace(target)
        return digest

    def put_json(self, value: BaseModel | dict[str, Any] | list[Any]) -> str:
        if isinstance(value, BaseModel):
            content = value.model_dump_json(indent=2).encode()
        else:
            content = json.dumps(value, indent=2, sort_keys=True).encode()
        return self.put_bytes(content + b"\n")

    def read_bytes(self, digest: str) -> bytes:
        if len(digest) != 64 or any(character not in "0123456789abcdef" for character in digest):
            raise ValueError("invalid artifact digest")
        return (self.objects / digest[:2] / digest[2:]).read_bytes()

    def read_json(self, digest: str) -> Any:
        return json.loads(self.read_bytes(digest))

    def set_ref(self, name: str, digest: str) -> None:
        if name.startswith("/") or ".." in Path(name).parts:
            raise ValueError("invalid artifact ref")
        self.read_bytes(digest)
        target = self.refs / name
        target.parent.mkdir(parents=True, exist_ok=True)
        temporary = target.with_suffix(target.suffix + ".tmp")
        temporary.write_text(digest + "\n", encoding="ascii")
        temporary.replace(target)

    def resolve(self, name: str) -> str:
        return (self.refs / name).read_text(encoding="ascii").strip()
