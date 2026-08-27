from __future__ import annotations

import json
import os
import shlex
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Optional, Protocol


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

    def run(
        self,
        command: tuple[str, ...],
        *,
        timeout_seconds: int = 900,
        envs: Optional[dict] = None,
    ) -> SandboxResult: ...

    def put(self, local: Path, remote: str) -> None: ...

    def get(self, remote: str, local: Path) -> None: ...


def _with_envs(command: tuple[str, ...], envs: Optional[dict]) -> tuple[str, ...]:
    if not envs:
        return tuple(command)
    prefix = tuple(f"{key}={value}" for key, value in sorted(envs.items()))
    return ("env",) + prefix + tuple(command)


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
    def load_private_env(path: Optional[Path] = None) -> None:
        """Load user-scoped E2B settings without ever storing them in Git."""
        config = path or Path.home() / ".config" / "lda-hm" / "e2b.env"
        if not config.is_file():
            return
        if config.stat().st_mode & 0o077:
            raise SandboxUnavailable(f"E2B config must be private (0600): {config}")
        for raw in config.read_text(encoding="utf-8").splitlines():
            line = raw.strip()
            if not line or line.startswith("#"):
                continue
            key, separator, value = line.partition("=")
            if not separator or not key:
                raise SandboxUnavailable(f"invalid E2B config line in {config}")
            os.environ.setdefault(key.strip(), value.strip())

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
        cls.load_private_env()
        cls.configure_shared_gateway()
        forwarded = {
            name: value
            for name in (
                "ANTHROPIC_API_KEY",
                "ANTHROPIC_AUTH_TOKEN",
                "ANTHROPIC_BASE_URL",
                "OPENAI_API_KEY",
                "OPENAI_BASE_URL",
                "GOOGLE_API_KEY",
                "GEMINI_API_KEY",
                "NO_PROXY",
                "no_proxy",
                "LDA_AGENT_BACKEND",
                "LDA_AGENT_PROVIDER",
                "LDA_AGENT_MODEL",
                "LDA_AGENT_MODEL_DRAFTER",
                "LDA_AGENT_MODEL_PLANNER",
                "LDA_AGENT_MODEL_ANALYST",
                "LDA_AGENT_MODEL_BUILDER",
                "LDA_AGENT_MODEL_REVIEWER",
                "LDA_AGENT_MODEL_SUPERVISOR",
                "LDA_AGENT_BACKEND_DRAFTER",
                "LDA_AGENT_BACKEND_PLANNER",
                "LDA_AGENT_BACKEND_ANALYST",
                "LDA_AGENT_BACKEND_BUILDER",
                "LDA_AGENT_BACKEND_REVIEWER",
                "LDA_AGENT_BACKEND_SUPERVISOR",
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
            instance = cls(client, sandbox_id=sandbox_id, cwd=cwd)
            instance._ensure_workdir()
            return instance
        try:
            client = client_factory(template=template, timeout=timeout, envs=forwarded)
        except TypeError:
            client = client_factory(template)
        sandbox_id = str(getattr(client, "sandbox_id", getattr(client, "id", "unknown")))
        instance = cls(client, sandbox_id=sandbox_id, cwd=cwd)
        instance._ensure_workdir()
        return instance

    def _ensure_workdir(self) -> None:
        """Create the configured cwd even when connecting to an older template."""
        if not hasattr(self.client, "commands"):
            return
        try:
            result = self.client.commands.run(
                f"mkdir -p {shlex.quote(self.cwd)}",
                cwd="/",
                timeout=60,
            )
        except Exception as error:
            raise SandboxUnavailable(
                f"could not prepare E2B workdir {self.cwd}: {error}"
            ) from error
        if int(getattr(result, "exit_code", 1)) != 0:
            raise SandboxUnavailable(
                f"could not create E2B workdir {self.cwd}: {getattr(result, 'stderr', '')}"
            )

    def run(
        self,
        command: tuple[str, ...],
        *,
        timeout_seconds: int = 900,
        envs: Optional[dict] = None,
    ) -> SandboxResult:
        if not command:
            raise ValueError("sandbox command must not be empty")
        command = _with_envs(command, envs)
        rendered = " ".join(shlex.quote(part) for part in command)
        started = time.monotonic()
        try:
            result = self.client.commands.run(rendered, cwd=self.cwd, timeout=timeout_seconds)
            exit_code = int(getattr(result, "exit_code", getattr(result, "exit_code", 0)))
            stdout = str(getattr(result, "stdout", ""))
            stderr = str(getattr(result, "stderr", ""))
        except Exception as error:  # transport errors are surfaced as failed results
            if hasattr(error, "exit_code"):
                exit_code = int(getattr(error, "exit_code"))
                stdout = str(getattr(error, "stdout", ""))
                stderr = str(getattr(error, "stderr", ""))
            else:
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

    def close(self) -> None:
        """Release the E2B sandbox (used by fresh certification sandboxes)."""
        kill = getattr(self.client, "kill", None)
        if callable(kill):
            kill()

    def bootstrap_assets(self, root: Path) -> None:
        """Overlay the checked-in harness/skills into the running template.

        This makes template drift visible and lets an existing shared template
        be upgraded without ever falling back to host execution.
        """
        mappings = (
            (root / "harness", "/opt/lda/harness"),
            (root / "checks", "/opt/lda/harness/checks"),
            (root / "skills", "/opt/lda/skills"),
            (root / "baseline", "/opt/lda/baseline"),
        )
        for directory in ("/opt/lda/control", "/opt/lda/review"):
            result = self.run(("mkdir", "-p", directory))
            if not result.ok:
                raise SandboxUnavailable(f"could not prepare E2B asset directory {directory}")
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

    def bootstrap_credentials(self) -> None:
        """Inject existing user-scoped Agent logins without copying them to Git.

        Per-role backends (e.g. a Claude Builder with a Codex Reviewer for
        cross-vendor review) may require more than one credential; every
        referenced backend must end up usable or the sandbox is refused.
        """
        codex_login = Path.home() / ".codex" / "auth.json"
        backends = {os.getenv("LDA_AGENT_BACKEND", "").strip()}
        for role in ("DRAFTER", "PLANNER", "ANALYST", "BUILDER", "REVIEWER", "SUPERVISOR"):
            backends.add(os.getenv(f"LDA_AGENT_BACKEND_{role}", "").strip())
        backends.discard("")
        if not backends:
            if os.getenv("ANTHROPIC_API_KEY") or os.getenv("ANTHROPIC_AUTH_TOKEN"):
                backends = {"claude"}
            elif codex_login.is_file() and codex_login.stat().st_size > 2:
                backends = {"codex"}
            else:
                backends = {"pi"}
        mappings_by_backend = {
            "pi": ((Path.home() / ".pi" / "agent" / "auth.json", "/home/user/.pi/agent/auth.json"),),
            "claude": ((Path.home() / ".claude" / ".credentials.json", "/home/user/.claude/.credentials.json"),),
            "codex": ((codex_login, "/home/user/.codex/auth.json"),),
        }
        unsupported = backends - set(mappings_by_backend)
        if unsupported:
            raise SandboxUnavailable(f"unsupported Agent backend: {sorted(unsupported)}")
        for backend in sorted(backends):
            environment_login = (
                backend == "claude"
                and bool(os.getenv("ANTHROPIC_API_KEY") or os.getenv("ANTHROPIC_AUTH_TOKEN"))
            ) or (backend == "codex" and bool(os.getenv("OPENAI_API_KEY")))
            if environment_login:
                continue
            installed = 0
            for local, remote in mappings_by_backend[backend]:
                if not local.is_file() or local.stat().st_size <= 2:
                    continue
                if local.stat().st_mode & 0o077:
                    raise SandboxUnavailable(
                        f"Agent credential must be private (0600): {local}"
                    )
                self.run(("mkdir", "-p", str(Path(remote).parent)))
                self.put(local, remote)
                result = self.run(("chmod", "0600", remote))
                if not result.ok:
                    raise SandboxUnavailable(f"could not protect Agent credential {remote}")
                installed += 1
            if installed == 0:
                raise SandboxUnavailable(
                    f"no login is available for the requested {backend} backend"
                )


class FakeSandbox:
    """Deterministic test double; never used by production defaults."""

    def __init__(self, results: dict[tuple[str, ...], SandboxResult] | None = None) -> None:
        self.sandbox_id = "fake-sandbox"
        self.results = results or {}
        self.commands: list[tuple[str, ...]] = []

    def run(
        self,
        command: tuple[str, ...],
        *,
        timeout_seconds: int = 900,
        envs: Optional[dict] = None,
    ) -> SandboxResult:
        command = _with_envs(tuple(command), envs)
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

    def close(self) -> None:
        pass


def sandbox_manifest(template: str = "lda-base", sandbox_id: str = "") -> str:
    return json.dumps(
        {
            "execution": "e2b",
            "template": template,
            "sandbox_id": sandbox_id,
            "host_fallback": False,
        },
        sort_keys=True,
    )
