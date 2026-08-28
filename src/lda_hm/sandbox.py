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
        api_url = os.getenv("E2B_API_URL")
        if not api_url or api_url != os.getenv("E2B_SANDBOX_URL"):
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
                # Fence/benchmark override variables are deliberately NOT
                # forwarded: one exported host variable must never be able to
                # silently replace a fence in production or certification
                # sandboxes.
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

    @classmethod
    def attach(cls, sandbox_id: str, *, cwd: str = "/opt/lda/work") -> "E2BSandbox":
        """Connect to an already-running sandbox (relay and watchdog side)."""
        cls.load_private_env()
        cls.configure_shared_gateway()
        try:
            from e2b import Sandbox as E2BSdkSandbox  # type: ignore
        except ImportError as error:
            raise SandboxUnavailable("E2B SDK is not installed") from error
        client = E2BSdkSandbox.connect(sandbox_id)
        return cls(client, sandbox_id=sandbox_id, cwd=cwd)

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
        content = local.read_bytes()
        if hasattr(self.client, "files") and hasattr(self.client.files, "write"):
            try:
                self.client.files.write(remote, content)
                return
            except Exception:
                # An attached client (Sandbox.connect) may lack the gateway
                # files route; the command channel always works.
                pass
        self._put_via_shell(content, remote)

    def _put_via_shell(self, content: bytes, remote: str) -> None:
        import base64 as _base64

        encoded = _base64.b64encode(content).decode("ascii")
        chunk = 120_000
        first = True
        for start in range(0, max(len(encoded), 1), chunk):
            piece = encoded[start : start + chunk]
            operator = ">" if first else ">>"
            first = False
            result = self.run(
                ("sh", "-c", f"printf %s {piece} {operator} {remote}.b64")
            )
            if not result.ok:
                raise SandboxUnavailable(f"could not stage upload for {remote}")
        result = self.run(
            ("sh", "-c", f"base64 -d {remote}.b64 > {remote} && rm -f {remote}.b64")
        )
        if not result.ok:
            raise SandboxUnavailable(f"could not decode upload for {remote}")

    def get(self, remote: str, local: Path) -> None:
        if hasattr(self.client, "files") and hasattr(self.client.files, "read"):
            try:
                content = self.client.files.read(remote)
                local.parent.mkdir(parents=True, exist_ok=True)
                local.write_bytes(
                    content if isinstance(content, bytes) else str(content).encode()
                )
                return
            except Exception:
                pass
        result = self.run(("sh", "-c", f"base64 {remote}"), timeout_seconds=900)
        if not result.ok:
            raise SandboxUnavailable(f"could not download {remote}")
        import base64 as _base64

        local.parent.mkdir(parents=True, exist_ok=True)
        local.write_bytes(_base64.b64decode("".join(result.stdout.split())))

    def close(self) -> None:
        """Release the E2B sandbox (used by fresh certification sandboxes)."""
        kill = getattr(self.client, "kill", None)
        if callable(kill):
            kill()

    def refresh_timeout(self, timeout_seconds: int) -> bool:
        """Re-arm the sandbox deadline so a long run outlives the default TTL."""
        set_timeout = getattr(self.client, "set_timeout", None)
        if not callable(set_timeout):
            return False
        try:
            set_timeout(timeout_seconds)
            return True
        except Exception:
            return False

    def sibling(self) -> "E2BSandbox":
        """A second client connection to the same sandbox.

        The BuilderWatchdog polls while the main thread is blocked inside a
        long agent command; sharing one client would make the watchdog either
        serialized (blind) or thread-unsafe. Never call close() on a sibling:
        the sandbox is owned by the primary connection.
        """
        try:
            from e2b import Sandbox as E2BSdkSandbox  # type: ignore
        except ImportError as error:
            raise SandboxUnavailable("E2B SDK is not installed") from error
        client = E2BSdkSandbox.connect(self.sandbox_id)
        return E2BSandbox(client, sandbox_id=self.sandbox_id, cwd=self.cwd)

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
            # The Humanize agent harness (vendored at a pinned commit): the
            # in-sandbox Builder works under its methodology - skills,
            # validator patterns, RLCR discipline - readable at /opt/lda/humanize.
            (root / "humanize", "/opt/lda/humanize"),
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
        self.run(
            (
                "sh",
                "-c",
                "find /opt/lda/harness /opt/lda/humanize -type f -name '*.sh' "
                "-exec chmod +x {} +",
            )
        )

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
