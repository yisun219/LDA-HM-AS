import asyncio
from pathlib import Path
from types import SimpleNamespace

from lda.config import E2BConfig
from lda.e2b.manager import E2BSandboxManager, SandboxLease, SandboxRole
from lda.state import EventStore

from .fakes import FakeSandbox


class Paginator:
    def __init__(self, values):
        self.values = values

    def __aiter__(self):
        self.iterator = iter(self.values)
        return self

    async def __anext__(self):
        try:
            return next(self.iterator)
        except StopIteration:
            raise StopAsyncIteration


class FakeAsyncSandbox(FakeSandbox):
    values = {}
    active = 0
    maximum = 0

    @classmethod
    async def create(cls, template=None, metadata=None, **kwargs):
        await asyncio.sleep(0.01)
        cls.active += 1
        cls.maximum = max(cls.maximum, cls.active)
        sandbox = cls(f"sandbox-{len(cls.values)}")
        sandbox.metadata = metadata or {}
        cls.values[sandbox.sandbox_id] = sandbox
        return sandbox

    @classmethod
    async def connect(cls, sandbox_id=None, **kwargs):
        return cls.values[sandbox_id]

    @classmethod
    def list(cls, query=None, **kwargs):
        metadata = getattr(query, "metadata", {}) or {}
        matches = [
            SimpleNamespace(sandbox_id=sandbox.sandbox_id, metadata=sandbox.metadata)
            for sandbox in cls.values.values()
            if all(sandbox.metadata.get(key) == value for key, value in metadata.items()) and not sandbox.killed
        ]
        return Paginator(matches)

    async def kill(self):
        if not self.killed:
            type(self).active -= 1
        return await super().kill()


async def test_create_reconnect_and_reap(monkeypatch, tmp_path: Path) -> None:
    FakeAsyncSandbox.values = {}
    FakeAsyncSandbox.active = 0
    monkeypatch.setenv("E2B_API_URL", "https://gateway")
    monkeypatch.setenv("E2B_SANDBOX_URL", "https://gateway")
    monkeypatch.setenv("E2B_API_KEY", "e2b_test_key_1234567890123456")
    manager = E2BSandboxManager(E2BConfig(), EventStore(tmp_path), max_live=2, sandbox_class=FakeAsyncSandbox)
    lease = SandboxLease.create(run_id="run", role=SandboxRole.WORKSPACE, template="base")
    first = await manager.create(lease)
    second = await manager.create(lease)
    assert first is second
    assert len(FakeAsyncSandbox.values) == 1
    killed = await manager.reap("run")
    assert killed == [first.sandbox_id]


async def test_global_sandbox_concurrency_limit(monkeypatch, tmp_path: Path) -> None:
    FakeAsyncSandbox.values = {}
    FakeAsyncSandbox.active = 0
    FakeAsyncSandbox.maximum = 0
    monkeypatch.setenv("E2B_API_URL", "https://gateway")
    monkeypatch.setenv("E2B_SANDBOX_URL", "https://gateway")
    monkeypatch.setenv("E2B_API_KEY", "e2b_test_key_1234567890123456")
    manager = E2BSandboxManager(E2BConfig(), EventStore(tmp_path), max_live=2, sandbox_class=FakeAsyncSandbox)
    leases = [SandboxLease.create(run_id="run", role=SandboxRole.WORKSPACE, template="base") for _ in range(4)]

    async def create_and_release(lease):
        await manager.create(lease)
        await asyncio.sleep(0.02)
        await manager.kill(lease.lease_id)

    await asyncio.gather(*(create_and_release(lease) for lease in leases))
    assert FakeAsyncSandbox.maximum <= 2


async def test_snapshot_releases_slot_and_kill_is_idempotent(monkeypatch, tmp_path: Path) -> None:
    FakeAsyncSandbox.values = {}
    FakeAsyncSandbox.active = 0
    monkeypatch.setenv("E2B_API_URL", "https://gateway")
    monkeypatch.setenv("E2B_SANDBOX_URL", "https://gateway")
    monkeypatch.setenv("E2B_API_KEY", "e2b_test_key_1234567890123456")
    manager = E2BSandboxManager(E2BConfig(), EventStore(tmp_path), max_live=1, sandbox_class=FakeAsyncSandbox)
    lease = SandboxLease.create(run_id="run", role=SandboxRole.WORKSPACE, template="base")
    await manager.create(lease)
    assert await manager.create_snapshot(lease.lease_id, name="baseline") == "snapshot-sandbox-0"
    await manager.kill(lease.lease_id)
    await manager.kill(lease.lease_id)

    replacement = SandboxLease.create(run_id="run", role=SandboxRole.WORKSPACE, template="base")
    await asyncio.wait_for(manager.create(replacement), timeout=1)
