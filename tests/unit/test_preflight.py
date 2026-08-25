from types import SimpleNamespace

from lda.config import E2BConfig
from lda.e2b.preflight import run_preflight

from .fakes import FakeResult


class Paginator:
    def __init__(self, values):
        self.values = iter(values)

    def __aiter__(self):
        return self

    async def __anext__(self):
        try:
            return next(self.values)
        except StopIteration:
            raise StopAsyncIteration


class Handle:
    pid = 42

    async def wait(self):
        return FakeResult()


class Commands:
    def __init__(self, sandbox):
        self.sandbox = sandbox

    async def run(self, command, background=False, **kwargs):
        if background:
            return Handle()
        if command == "uname -a":
            return FakeResult(0, "Linux fixture", "")
        if command == "cat /etc/os-release":
            return FakeResult(0, "VERSION_ID=26.04", "")
        if command == "lscpu":
            return FakeResult(0, "Model: 207", "")
        if "printf persistent" in command or command == "cat /tmp/lda-preflight/value":
            return FakeResult(0, "persistent", "")
        if command == "printf foreground":
            return FakeResult(0, "foreground", "")
        return FakeResult()

    async def connect(self, pid):
        assert pid == 42
        return Handle()


class FakePreflightSandbox:
    values = {}

    def __init__(self, sandbox_id, metadata):
        self.sandbox_id = sandbox_id
        self.metadata = metadata
        self.commands = Commands(self)
        self.killed = False

    @classmethod
    async def create(cls, template=None, metadata=None, **kwargs):
        sandbox = cls(f"sandbox-{len(cls.values)}", metadata or {})
        cls.values[sandbox.sandbox_id] = sandbox
        return sandbox

    @classmethod
    async def connect(cls, sandbox_id=None, **kwargs):
        return cls.values[sandbox_id]

    @classmethod
    def list(cls, query=None, **kwargs):
        metadata = getattr(query, "metadata", {}) or {}
        return Paginator(
            SimpleNamespace(sandbox_id=item.sandbox_id)
            for item in cls.values.values()
            if not item.killed and all(item.metadata.get(key) == value for key, value in metadata.items())
        )

    async def create_snapshot(self, name=None):
        return SimpleNamespace(snapshot_id="snapshot-1")

    async def fork(self, timeout=None, count=None):
        fork = await type(self).create(metadata={**self.metadata, "fork": "true"})
        return [fork]

    async def kill(self):
        self.killed = True
        return True


class FakeTemplate:
    @staticmethod
    def exists(name):
        return name == "base"


async def test_complete_preflight(monkeypatch) -> None:
    FakePreflightSandbox.values = {}
    monkeypatch.setenv("E2B_API_URL", "https://gateway")
    monkeypatch.setenv("E2B_SANDBOX_URL", "https://gateway")
    monkeypatch.setenv("E2B_API_KEY", "e2b_test_key_1234567890123456")
    report = await run_preflight(
        E2BConfig(base_template="base"),
        sandbox_class=FakePreflightSandbox,
        template_class=FakeTemplate,
    )
    assert report.background_pid == 42
    assert report.snapshot_id == "snapshot-1"
    assert report.fork_supported
    assert report.checks["metadata"] == "ok"
    assert all(item.killed for item in FakePreflightSandbox.values.values())
