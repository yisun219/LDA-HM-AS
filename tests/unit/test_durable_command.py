from __future__ import annotations

import asyncio
from types import SimpleNamespace

from lda.e2b.durable import run_durable_command


class Files:
    def __init__(self) -> None:
        self.values: dict[str, bytes] = {}

    async def write(self, path: str, value) -> None:
        self.values[path] = str(value).encode()

    async def read(self, path: str):
        return self.values[path]


class Commands:
    def __init__(self, owner) -> None:
        self.owner = owner
        self.connects = 0

    async def run(self, command: str, **kwargs):
        self.owner.files.values["/opt/lda/command-state/test/stdout"] = b"finished\n"
        self.owner.files.values["/opt/lda/command-state/test/stderr"] = b"warning\n"
        self.owner.files.values["/opt/lda/command-state/test/status"] = b"0\n"
        return SimpleNamespace(exit_code=0, stdout="42\n", stderr="")

    async def connect(self, pid: int):
        self.connects += 1

        async def wait():
            if self.connects == 1:
                raise ConnectionError("stream disconnected")
            await asyncio.sleep(0)

        return SimpleNamespace(wait=wait)


class Sandbox:
    instances: dict[str, "Sandbox"] = {}

    def __init__(self, sandbox_id: str = "sandbox") -> None:
        self.sandbox_id = sandbox_id
        self.files = Files()
        self.commands = Commands(self)
        type(self).instances[sandbox_id] = self

    @classmethod
    async def connect(cls, sandbox_id: str):
        return cls.instances[sandbox_id]


async def test_durable_command_uses_persisted_result_after_stream_disconnect() -> None:
    result = await run_durable_command(
        Sandbox(),
        "long-build",
        timeout=5,
        command_id="test",
        reconnect_interval=0,
    )
    assert result.exit_code == 0
    assert result.pid == 42
    assert result.stdout == "finished\n"
    assert result.stderr == "warning\n"
