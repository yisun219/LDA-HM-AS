from __future__ import annotations

import json
import os
import shlex
import uuid
from dataclasses import dataclass
from typing import Any

from lda.e2b.gateway import SharedGateway


@dataclass
class Sandbox:
    sandbox_id: str
    metadata: dict[str, str]
    alive: bool = True
    native: Any = None


class E2BClient:
    """Small SDK-neutral client boundary. Production calls are intentionally fail-closed."""

    def __init__(self, gateway: SharedGateway | None = None, *, fake: bool = False,
                 template_fallback: str | None = None, allow_agent_stub: bool = False):
        self.gateway = gateway or SharedGateway()
        self.fake = fake
        self.template_fallback = template_fallback or os.environ.get("LDA_E2B_TEMPLATE_FALLBACK")
        self.allow_agent_stub = allow_agent_stub
        self.sandboxes: dict[str, Sandbox] = {}
        self._fake_files: dict[tuple[str, str], str] = {}

    def _require_runtime(self) -> None:
        if self.fake:
            return
        if not self.gateway.api_key:
            raise RuntimeError("E2B_API_KEY is missing; refusing to run outside E2B")

    @staticmethod
    def _private_env_file() -> str:
        return os.environ.get("LDA_CODEX_ENV_FILE", os.path.expanduser("~/.config/lda/codex.env"))

    def _agent_env(self) -> dict[str, str]:
        values: dict[str, str] = {}
        path = self._private_env_file()
        if os.path.exists(path):
            with open(path, encoding="utf-8") as fh:
                for line in fh:
                    line = line.strip()
                    if not line or line.startswith("#") or "=" not in line:
                        continue
                    key, value = line.split("=", 1)
                    values[key.strip()] = value.strip().strip("\"'")
        for key in ("OPENAI_API_KEY", "CODEX_API_KEY", "OPENAI_BASE_URL"):
            if os.environ.get(key):
                values[key] = os.environ[key]
        if values.get("CODEX_API_KEY") and not values.get("OPENAI_API_KEY"):
            values["OPENAI_API_KEY"] = values["CODEX_API_KEY"]
        return {key: value for key, value in values.items() if key in {"OPENAI_API_KEY", "OPENAI_BASE_URL"}}

    def codex_command(self, prompt: str) -> str:
        """Build a Codex CLI invocation using an explicit custom model provider."""
        env = self._agent_env()
        args = ["codex", "exec", "--skip-git-repo-check", "--json",
                "-c", "model_provider=\"fact\"",
                "-c", "model_providers.fact.name=\"Fact Gateway\"",
                "-c", f"model_providers.fact.base_url={shlex.quote(env.get('OPENAI_BASE_URL', 'https://api.openai.com/v1'))}",
                "-c", "model_providers.fact.env_key=\"OPENAI_API_KEY\"",
                "-c", "model_providers.fact.wire_api=\"responses\"", prompt]
        return " ".join(shlex.quote(arg) for arg in args)

    def create(self, metadata: dict[str, str]) -> Sandbox:
        self._require_runtime()
        lease = metadata.get("lease_id") or uuid.uuid4().hex
        if lease in self.sandboxes:
            return self.sandboxes[lease]
        if not self.fake:
            try:
                from e2b import Sandbox as NativeSandbox
                headers = self.gateway.headers()
                template = metadata.get("template") or self.template_fallback or "lda-controller"
                role = metadata.get("role", "")
                agent_role = role in {"Argus Manager", "World State Summarizer", "Research Curator", "Mission Planner", "Profiler", "Builder", "Reviewer", "Trace Auditor", "Outcome Classifier", "Capability Planner", "Capability Builder"}
                agent_env = self._agent_env() if agent_role else {}
                native = NativeSandbox.create(template=template,
                    timeout=metadata.get("timeout", 3600), metadata=dict(metadata), envs=agent_env,
                    secure=True, allow_internet_access=agent_role,
                    api_key=self.gateway.api_key, access_token=self.gateway.config.access_token,
                    api_url=self.gateway.config.api_url, sandbox_url=self.gateway.config.sandbox_url,
                    headers=headers)
                sandbox = Sandbox(native.sandbox_id, dict(metadata), native=native)
            except Exception as exc:
                raise RuntimeError(f"E2B Sandbox.create failed: {exc}") from exc
        else:
            sandbox = Sandbox("sbx_" + uuid.uuid4().hex[:16], dict(metadata))
        self.sandboxes[lease] = sandbox
        return sandbox

    def connect(self, sandbox_id: str) -> Sandbox:
        self._require_runtime()
        for sandbox in self.sandboxes.values():
            if sandbox.sandbox_id == sandbox_id and sandbox.alive:
                return sandbox
        if self.fake:
            raise RuntimeError("unknown sandbox")
        try:
            from e2b import Sandbox as NativeSandbox
            native = NativeSandbox.connect(sandbox_id, api_key=self.gateway.api_key,
                access_token=self.gateway.config.access_token, api_url=self.gateway.config.api_url,
                sandbox_url=self.gateway.config.sandbox_url, headers=self.gateway.headers())
            sandbox = Sandbox(sandbox_id, {"project": "lda"}, native=native)
            self.sandboxes[sandbox_id] = sandbox
            return sandbox
        except Exception as exc:
            raise RuntimeError(f"E2B Sandbox.connect failed: {exc}") from exc

    def command(self, sandbox: Sandbox, command: str, *, background: bool = False) -> dict[str, Any]:
        self._require_runtime()
        if not sandbox.alive:
            raise RuntimeError("sandbox is not alive")
        if not self.fake:
            try:
                result = sandbox.native.commands.run(command, background=background)
            except Exception as exc:
                if self.allow_agent_stub and os.environ.get("LDA_ALLOW_AGENT_STUB") == "1":
                    return {"status": "diagnostic_stub", "exit_code": 0, "stdout": "", "stderr": str(exc), "command": command}
                raise
            if background:
                return {"pid": getattr(result, "pid", None), "status": "started", "command": command}
            return {"status": "completed", "exit_code": result.exit_code, "stdout": result.stdout, "stderr": result.stderr, "command": command}
        if background:
            return {"pid": 1, "status": "started", "command": command}
        return {"status": "completed", "exit_code": 0, "stdout": "", "stderr": "", "command": command}

    def filesystem_write(self, sandbox: Sandbox, path: str, content: str) -> None:
        self._require_runtime()
        if not self.fake:
            sandbox.native.files.write(path, content)
        else:
            self._fake_files[(sandbox.sandbox_id, path)] = content

    def filesystem_read(self, sandbox: Sandbox, path: str) -> str:
        self._require_runtime()
        if not self.fake:
            return sandbox.native.files.read(path)
        return self._fake_files.get((sandbox.sandbox_id, path), "")

    def snapshot(self, sandbox: Sandbox) -> dict[str, Any]:
        self._require_runtime()
        return {"snapshot_id": "snap_" + sandbox.sandbox_id, "sandbox_id": sandbox.sandbox_id}

    def fork(self, sandbox: Sandbox, metadata: dict[str, str]) -> Sandbox:
        snapshot = self.snapshot(sandbox)
        child = self.create({**metadata, "snapshot_id": snapshot["snapshot_id"]})
        return child

    def kill(self, sandbox: Sandbox) -> None:
        if not self.fake and sandbox.native is not None:
            sandbox.native.kill()
        sandbox.alive = False

    def reap(self, run_id: str) -> int:
        count = 0
        for sandbox in self.sandboxes.values():
            if sandbox.metadata.get("run_id") == run_id and sandbox.alive:
                sandbox.alive = False
                count += 1
        return count
