from __future__ import annotations

from dataclasses import dataclass
import re
from types import SimpleNamespace


@dataclass
class FakeResult:
    exit_code: int = 0
    stdout: str = ""
    stderr: str = ""
    pid: int | None = None


class FakeFiles:
    def __init__(self) -> None:
        self.values: dict[str, bytes] = {}

    async def write(self, path: str, value) -> None:
        self.values[path] = value if isinstance(value, bytes) else str(value).encode()

    async def read(self, path: str):
        return self.values[path]


class FakeCommands:
    def __init__(self, owner) -> None:
        self.owner = owner
        self.calls: list[str] = []

    async def run(self, command: str, **kwargs):
        self.calls.append(command)
        result = self._result(command)
        if "tar -C /home/agent/.codex -czf" in command:
            match = re.search(r"-czf ([^ ]+)", command)
            if match:
                self.owner.files.values[match.group(1).strip("'")] = b"session-checkpoint"
        if "/opt/lda/command-state/" in command:
            match = re.search(r"(/opt/lda/command-state/[0-9a-f]+)", command)
            if match:
                root = match.group(1)
                self.owner.files.values[f"{root}/stdout"] = result.stdout.encode()
                self.owner.files.values[f"{root}/stderr"] = result.stderr.encode()
                self.owner.files.values[f"{root}/status"] = f"{result.exit_code}\n".encode()
            return FakeResult(stdout="1234\n")
        return result

    def _result(self, command: str) -> FakeResult:
        if self.owner.fail_token and self.owner.fail_token in command:
            return FakeResult(1, "", "forced failure")
        if "find /opt/lda/baseline" in command and "*.deb" in command:
            paths = sorted(
                path for path in self.owner.files.values
                if path.startswith("/opt/lda/baseline/") and path.endswith(".deb")
            )
            return FakeResult(0, "\n".join(paths) + ("\n" if paths else ""), "")
        if "run-paired-probe-benchmark.py" in command:
            import json

            layer = "e2e" if "--layer e2e" in command else "micro"
            baseline = [1.0 + (index % 2) * 0.0001 for index in range(30)]
            candidate = [value / 1.05 for value in baseline]
            return FakeResult(
                0,
                json.dumps(
                    {
                        "name": "fixture",
                        "layer": layer,
                        "baseline": baseline,
                        "candidate": candidate,
                        "warmups": 10,
                        "seed": 2604,
                        "randomized_order": ["baseline"] * 30,
                        "cpu_affinity": "0",
                        "numa_policy": "local",
                        "environment": {"cpu": "fixture"},
                    }
                ),
                "",
            )
        return FakeResult()

    async def connect(self, pid: int):
        return SimpleNamespace(wait=self._wait)

    async def _wait(self):
        return FakeResult()


class FakeSandbox:
    def __init__(self, sandbox_id: str = "sandbox", fail_token: str = "") -> None:
        self.sandbox_id = sandbox_id
        self.fail_token = fail_token
        self.files = FakeFiles()
        self.commands = FakeCommands(self)
        self.killed = False

    async def kill(self) -> bool:
        self.killed = True
        return True

    async def pause(self) -> bool:
        return True

    async def create_snapshot(self, name=None):
        return SimpleNamespace(snapshot_id=f"snapshot-{self.sandbox_id}")
