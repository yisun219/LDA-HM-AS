from __future__ import annotations

import json
import os
import shlex
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Protocol


class SandboxUnavailable(RuntimeError):
    pass


@dataclass(frozen=True)
class SandboxResult:
    command: tuple[str, ...]
    exit_code: int
    stdout: str
    stderr: str
    duration_seconds: float
    sandbox_id: str

    @property
    def ok(self) -> bool:
        return self.exit_code == 0


class Sandbox(Protocol):
    sandbox_id: str

    def run(self, command: tuple[str, ...], *, timeout_seconds: int = 900) -> SandboxResult: ...

    def put(self, local: Path, remote: str) -> None: ...

    def get(self, remote: str, local: Path) -> None: ...


class E2BSandbox:
    """E2B-only execution adapter.

    The actual SDK client is injected so the control plane is testable without
    credentials. No fallback to the host shell is provided by design.
    """

    def __init__(self, client: Any, *, sandbox_id: str, cwd: str = "/opt/lda/work") -> None:
        self.client = client
        self.sandbox_id = sandbox_id
        self.cwd = cwd

    @staticmethod
    def configure_shared_gateway() -> None:
        if os.getenv("E2B_API_URL") != os.getenv("E2B_SANDBOX_URL"):
            return
        try:
            from e2b.connection_config import ConnectionConfig  # type: ignore
        except ImportError:
            return
        if getattr(ConnectionConfig.sandbox_headers.fget, "_lda_gateway", False):
            return
        original = ConnectionConfig.sandbox_headers.fget
        if original is None:
            return

        def sandbox_headers(config):
            headers = dict(original(config))
            headers["X-API-KEY"] = config.api_key
            return headers

        sandbox_headers._lda_gateway = True
        ConnectionConfig.sandbox_headers = property(sandbox_headers)

    @classmethod
    def connect(
        cls,
        template: str = "lda-base",
        *,
        client_factory: Callable[..., Any] | None = None,
        timeout: int = 3600,
        cwd: str = "/opt/lda/work",
    ) -> "E2BSandbox":
        cls.configure_shared_gateway()
        forwarded = {
            name: value
            for name in (
                "ANTHROPIC_API_KEY",
                "OPENAI_API_KEY",
                "GOOGLE_API_KEY",
                "GEMINI_API_KEY",
                "LDA_AGENT_PROVIDER",
                "LDA_AGENT_MODEL",
                "LDA_AGENT_THINKING",
                "LDA_BASELINE_TEST_COMMAND",
                "LDA_DEPENDENCY_TEST_COMMAND",
                "LDA_ABI_FENCE_COMMAND",
                "LDA_FFI_FENCE_COMMAND",
                "LDA_BEHAVIOR_FENCE_COMMAND",
                "LDA_PACKAGE_LIFECYCLE_COMMAND",
                "LDA_SECURITY_FENCE_COMMAND",
                "LDA_RESULT_EQUIVALENCE_COMMAND",
                "LDA_MICRO_BASELINE_COMMAND",
                "LDA_MICRO_BENCHMARK_COMMAND",
                "LDA_END_TO_END_BASELINE_COMMAND",
                "LDA_END_TO_END_BENCHMARK_COMMAND",
            )
            if (value := os.getenv(name))
        }
        if client_factory is None:
            try:
                from e2b import Sandbox as E2BSdkSandbox  # type: ignore
            except ImportError as error:
                raise SandboxUnavailable("E2B SDK is not installed; refusing host execution") from error
            client = E2BSdkSandbox.create(template=template, timeout=timeout, envs=forwarded)
            sandbox_id = str(getattr(client, "sandbox_id", getattr(client, "id", "unknown")))
            return cls(client, sandbox_id=sandbox_id, cwd=cwd)
        try:
            client = client_factory(template=template, timeout=timeout, envs=forwarded)
        except TypeError:
            client = client_factory(template)
        sandbox_id = str(getattr(client, "sandbox_id", getattr(client, "id", "unknown")))
        return cls(client, sandbox_id=sandbox_id, cwd=cwd)

    def run(self, command: tuple[str, ...], *, timeout_seconds: int = 900) -> SandboxResult:
        if not command:
            raise ValueError("sandbox command must not be empty")
        rendered = " ".join(shlex.quote(part) for part in command)
        started = time.monotonic()
        try:
            result = self.client.commands.run(rendered, cwd=self.cwd, timeout=timeout_seconds)
            exit_code = int(getattr(result, "exit_code", getattr(result, "exit_code", 0)))
            stdout = str(getattr(result, "stdout", ""))
            stderr = str(getattr(result, "stderr", ""))
        except Exception as error:  # transport errors are surfaced as failed results
            exit_code, stdout, stderr = 125, "", repr(error)
        return SandboxResult(tuple(command), exit_code, stdout, stderr, time.monotonic() - started, self.sandbox_id)

    def put(self, local: Path, remote: str) -> None:
        if not local.is_file():
            raise FileNotFoundError(local)
        if hasattr(self.client, "files") and hasattr(self.client.files, "write"):
            self.client.files.write(remote, local.read_bytes())
            return
        raise SandboxUnavailable("connected E2B client has no file upload API")

    def get(self, remote: str, local: Path) -> None:
        if hasattr(self.client, "files") and hasattr(self.client.files, "read"):
            content = self.client.files.read(remote)
            local.parent.mkdir(parents=True, exist_ok=True)
            local.write_bytes(content if isinstance(content, bytes) else str(content).encode())
            return
        raise SandboxUnavailable("connected E2B client has no file download API")

    def bootstrap_assets(self, root: Path) -> None:
        """Overlay the checked-in harness/skills into the running template.

        This makes template drift visible and lets an existing shared template
        be upgraded without ever falling back to host execution.
        """
        mappings = (
            (root / "harness", "/opt/lda/harness"),
            (root / "checks", "/opt/lda/harness/checks"),
            (root / "skills", "/opt/lda/skills"),
        )
        for source, destination in mappings:
            for local in sorted(source.rglob("*")):
                if not local.is_file():
                    continue
                remote = destination + "/" + str(local.relative_to(source)).replace("\\", "/")
                parent = str(Path(remote).parent)
                self.run(("mkdir", "-p", parent))
                self.put(local, remote)
        self.run(("chmod", "+x", "/opt/lda/harness/lda-agent-harness.sh"))
        self.run(("find", "/opt/lda/harness/checks", "-type", "f", "-name", "*.sh", "-exec", "chmod", "+x", "{}", ";"))


class FakeSandbox:
    """Deterministic test double; never used by production defaults."""

    def __init__(self, results: dict[tuple[str, ...], SandboxResult] | None = None) -> None:
        self.sandbox_id = "fake-sandbox"
        self.results = results or {}
        self.commands: list[tuple[str, ...]] = []

    def run(self, command: tuple[str, ...], *, timeout_seconds: int = 900) -> SandboxResult:
        self.commands.append(command)
        return self.results.get(
            command,
            SandboxResult(command, 0, "", "", 0.001, self.sandbox_id),
        )

    def put(self, local: Path, remote: str) -> None:
        if not local.exists():
            raise FileNotFoundError(local)

    def get(self, remote: str, local: Path) -> None:
        local.parent.mkdir(parents=True, exist_ok=True)
        local.write_text("", encoding="utf-8")


def sandbox_manifest(template: str = "lda-base") -> str:
    return json.dumps({"execution": "e2b", "template": template, "host_fallback": False}, sort_keys=True)
