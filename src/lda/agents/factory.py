from __future__ import annotations

import json
import shlex
import asyncio
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol
from uuid import uuid4

from lda.artifacts import ArtifactStore
from lda.e2b import E2BSandboxManager, SandboxLease, SandboxRole, run_durable_command
from lda.gateway import CapabilityAuthority
from lda.models import AgentResult, AgentSpec, SessionPolicy
from lda.state import EventStore


class CodexBackend(Protocol):
    async def run(
        self,
        sandbox: Any,
        spec: AgentSpec,
        *,
        prompt: str,
        schema: dict[str, Any],
        thread_id: str | None,
        capability_token: str,
    ) -> AgentResult: ...


class CodexCliBackend:
    """Structured Codex CLI backend running only inside lda-agent-runtime."""

    async def run(
        self,
        sandbox: Any,
        spec: AgentSpec,
        *,
        prompt: str,
        schema: dict[str, Any],
        thread_id: str | None,
        capability_token: str,
    ) -> AgentResult:
        turn_id = uuid4().hex
        root = f"/opt/lda/agent-state/{turn_id}"
        await sandbox.commands.run(f"mkdir -p {shlex.quote(root)}")
        await sandbox.files.write(f"{root}/prompt.txt", prompt)
        await sandbox.files.write(f"{root}/schema.json", json.dumps(schema, sort_keys=True))
        model = shlex.quote(spec.model)
        effort = shlex.quote(spec.reasoning_effort)
        output = f"{root}/output.json"
        trace = f"{root}/trace.jsonl"
        capability = shlex.quote(capability_token)
        environment = (
            f"LDA_CAPABILITY_TOKEN={capability} "
            f"LDA_RUN_ID={shlex.quote(spec.run_id)} "
            f"LDA_MISSION_ID={shlex.quote(spec.mission_id)} "
            f"LDA_CANDIDATE_ID={shlex.quote(spec.candidate_id or '')} "
        )
        if thread_id:
            command = (
                f"{environment} codex --disable plugins --disable skill_search --disable skill_mcp_dependency_install "
                f"exec resume --json --model {model} "
                f"--config model_reasoning_effort={effort} "
                f"--output-schema {root}/schema.json --output-last-message {output} "
                f"{shlex.quote(thread_id)} \"$(cat {root}/prompt.txt)\" >{trace}"
            )
        else:
            sandbox_mode = "workspace-write" if spec.role == "builder" else "read-only"
            command = (
                f"{environment} codex --disable plugins --disable skill_search --disable skill_mcp_dependency_install "
                f"exec --json --model {model} "
                f"--config model_reasoning_effort={effort} --sandbox {sandbox_mode} "
                f"--cd /opt/lda/work --skip-git-repo-check "
                f"--output-schema {root}/schema.json --output-last-message {output} "
                f"\"$(cat {root}/prompt.txt)\" >{trace}"
            )
        command = f"rm -f {shlex.quote(output)} {shlex.quote(trace)}; {command}"
        completed = None
        raw_trace = b""
        for attempt in range(5):
            completed = await run_durable_command(
                sandbox,
                f"sh -lc {shlex.quote(command)}",
                timeout=spec.timeout_seconds,
            )
            try:
                raw_trace_value = await sandbox.files.read(trace)
                raw_trace = raw_trace_value if isinstance(raw_trace_value, bytes) else str(raw_trace_value).encode()
            except Exception:
                raw_trace = b""
            if completed.exit_code == 0:
                try:
                    candidate_output = await sandbox.files.read(output)
                except Exception:
                    candidate_output = b""
                rendered_output = candidate_output if isinstance(candidate_output, bytes) else str(candidate_output).encode()
                if rendered_output.strip():
                    break
                if attempt == 4:
                    raise RuntimeError("Codex completed without a structured output file")
                await asyncio.sleep(2 ** attempt)
                continue
            diagnostic = (completed.stderr or "") + "\n" + raw_trace.decode(errors="replace")
            transient = any(
                marker in diagnostic.lower()
                for marker in ("502 bad gateway", "503 service unavailable", "429 too many", "timed out", "connection reset", "temporarily unavailable")
            )
            if not transient or attempt == 4:
                raise RuntimeError(f"Codex {spec.role} failed (exit={completed.exit_code}): {diagnostic[-2000:]}")
            await asyncio.sleep(2 ** attempt)
        if completed is None or completed.exit_code != 0:
            raise RuntimeError(f"Codex {spec.role} failed without a command result")
        raw_output = await sandbox.files.read(output)
        output_text = raw_output.decode() if isinstance(raw_output, bytes) else str(raw_output)
        trace_text = raw_trace.decode() if isinstance(raw_trace, bytes) else str(raw_trace)
        parsed = json.loads(output_text)
        actual_thread = thread_id
        if not actual_thread:
            for line in trace_text.splitlines():
                event = json.loads(line)
                if event.get("type") == "thread.started":
                    actual_thread = str(event["thread_id"])
                    break
        if not actual_thread:
            raise RuntimeError("Codex trace did not contain a thread ID")
        return AgentResult(
            agent_id=turn_id,
            thread_id=actual_thread,
            output=parsed,
            trace_ref=trace,
        )


class CodexSdkBackend:
    """Adapter for the optional openai-codex Python SDK."""

    async def run(
        self,
        sandbox: Any,
        spec: AgentSpec,
        *,
        prompt: str,
        schema: dict[str, Any],
        thread_id: str | None,
        capability_token: str,
    ) -> AgentResult:
        request = {
            "prompt": prompt,
            "schema": schema,
            "thread_id": thread_id,
            "model": spec.model,
            "reasoning_effort": spec.reasoning_effort,
            "capability_token": capability_token,
        }
        request_path = f"/tmp/lda-codex-sdk-{uuid4().hex}.json"
        await sandbox.files.write(request_path, json.dumps(request))
        result = await sandbox.commands.run(
            f"python3 -m lda.codex.sdk_runner {request_path}", timeout=spec.timeout_seconds
        )
        if result.exit_code != 0:
            raise RuntimeError(f"openai-codex SDK backend failed: {result.stderr[-2000:]}")
        value = json.loads(result.stdout)
        return AgentResult.model_validate(value)


class FakeCodexBackend:
    def __init__(self, outputs: list[dict[str, Any]] | None = None) -> None:
        self.outputs = list(outputs or [{}])
        self.calls: list[tuple[AgentSpec, str | None]] = []

    async def run(
        self,
        sandbox: Any,
        spec: AgentSpec,
        *,
        prompt: str,
        schema: dict[str, Any],
        thread_id: str | None,
        capability_token: str,
    ) -> AgentResult:
        self.calls.append((spec, thread_id))
        output = self.outputs.pop(0) if self.outputs else {}
        return AgentResult(
            agent_id=uuid4().hex,
            thread_id=thread_id or uuid4().hex,
            output=output,
            trace_ref=f"fake://trace/{uuid4().hex}",
        )


@dataclass
class AgentHandle:
    spec: AgentSpec
    sandbox: Any
    lease: SandboxLease
    backend: CodexBackend
    capability_token: str
    artifacts: ArtifactStore
    store: EventStore
    manager: E2BSandboxManager
    session_semaphore: asyncio.Semaphore
    thread_id: str | None = None
    cancelled: bool = False

    @property
    def key(self) -> str:
        return ":".join(
            [self.spec.run_id, self.spec.mission_id, self.spec.candidate_id or "", self.spec.role, self.spec.independence_group]
        )

    async def run(self, input_ref: str) -> AgentResult:
        if self.cancelled:
            raise RuntimeError("agent was cancelled")
        prompt = self.artifacts.read_bytes(input_ref).decode()
        schema = self.artifacts.read_json(self.spec.output_schema)
        result = await self.backend.run(
            self.sandbox,
            self.spec,
            prompt=prompt,
            schema=schema,
            thread_id=None,
            capability_token=self.capability_token,
        )
        result = await self._persist_trace(result)
        self.thread_id = result.thread_id
        if self.spec.session_policy is SessionPolicy.PERSISTENT:
            self.store.save_thread(self.key, result.thread_id, result.checkpoint_ref)
        return result

    async def resume(self, input_ref: str) -> AgentResult:
        if self.spec.session_policy is not SessionPolicy.PERSISTENT:
            raise RuntimeError("fresh-session agent cannot be resumed")
        saved = self.store.load_thread(self.key)
        self.thread_id = self.thread_id or (saved[0] if saved else None)
        if not self.thread_id:
            raise RuntimeError("persistent thread has no checkpoint")
        prompt = self.artifacts.read_bytes(input_ref).decode()
        schema = self.artifacts.read_json(self.spec.output_schema)
        result = await self.backend.run(
            self.sandbox,
            self.spec,
            prompt=prompt,
            schema=schema,
            thread_id=self.thread_id,
            capability_token=self.capability_token,
        )
        result = await self._persist_trace(result)
        self.thread_id = result.thread_id
        self.store.save_thread(self.key, result.thread_id, result.checkpoint_ref)
        return result

    async def _persist_trace(self, result: AgentResult) -> AgentResult:
        if not result.trace_ref.startswith("/"):
            return result
        raw = await self.sandbox.files.read(result.trace_ref)
        content = raw if isinstance(raw, bytes) else str(raw).encode()
        reference = self.artifacts.put_bytes(content)
        return result.model_copy(update={"trace_ref": reference})

    async def checkpoint(self) -> str:
        reference = await self.manager.create_snapshot(self.lease.lease_id)
        if self.thread_id:
            self.store.save_thread(self.key, self.thread_id, reference)
        return reference

    async def cancel(self) -> None:
        if self.cancelled:
            return
        self.cancelled = True
        try:
            await self.manager.kill(self.lease.lease_id)
        finally:
            self.session_semaphore.release()


class AgentFactory:
    def __init__(
        self,
        manager: E2BSandboxManager,
        artifacts: ArtifactStore,
        store: EventStore,
        authority: CapabilityAuthority,
        *,
        gateway_url: str,
        codex_auth_path: Path = Path("/opt/lda/secrets/codex-auth.json"),
        codex_provider_path: Path = Path("/opt/lda/secrets/codex-provider.json"),
        max_live_sessions: int = 8,
        backends: dict[str, CodexBackend] | None = None,
    ) -> None:
        self.manager = manager
        self.artifacts = artifacts
        self.store = store
        self.authority = authority
        self.gateway_url = gateway_url
        self.codex_auth_path = codex_auth_path
        self.codex_provider_path = codex_provider_path
        self._session_semaphore = asyncio.Semaphore(max_live_sessions)
        self._bridge_processes: dict[str, int] = {}
        self.backends = backends or {
            "codex-sdk": CodexSdkBackend(),
            "codex-cli": CodexCliBackend(),
        }

    async def spawn(self, spec: AgentSpec) -> AgentHandle:
        self._validate_independence(spec)
        await self._session_semaphore.acquire()
        provider: dict[str, str] | None = None
        if spec.backend in {"codex-sdk", "codex-cli"} and self.codex_provider_path.is_file():
            provider = json.loads(self.codex_provider_path.read_text(encoding="utf-8"))
            if not provider.get("base_url") or not provider.get("api_key"):
                self._session_semaphore.release()
                raise RuntimeError("controller Codex provider configuration is incomplete")
        lease = SandboxLease.create(
            run_id=spec.run_id,
            mission_id=spec.mission_id,
            candidate_id=spec.candidate_id or "",
            role=SandboxRole.AGENT,
            template=spec.runtime_template,
        )
        try:
            sandbox = await self.manager.create(
                lease,
                timeout=spec.timeout_seconds,
                agent_runtime=True,
                envs={
                    "LDA_AGENT_ROLE": spec.role,
                    "LDA_GATEWAY_URL": self.gateway_url,
                    **({"LDA_CODEX_API_KEY": provider["api_key"]} if provider else {}),
                },
            )
        except Exception:
            self._session_semaphore.release()
            raise
        try:
            if provider:
                bridge_process = await sandbox.commands.run(
                    "nohup setsid sh -lc 'exec /opt/lda/venv/bin/python3 /opt/lda/venv/lib/python3.12/site-packages/lda/codex/bridge.py --port 8787' >/opt/lda/codex-bridge.log 2>&1 </dev/null & printf '%s' $!"
                )
                if bridge_process.exit_code != 0 or not bridge_process.stdout.strip().isdigit():
                    raise RuntimeError("could not start the in-sandbox Codex protocol bridge")
                self._bridge_processes[lease.lease_id] = int(bridge_process.stdout.strip())
                ready = False
                for _ in range(20):
                    try:
                        check = await sandbox.commands.run(
                            "/opt/lda/venv/bin/python3 -c 'import socket; s=socket.create_connection((\"127.0.0.1\",8787), timeout=1); s.close()'"
                        )
                        if check.exit_code == 0:
                            ready = True
                            break
                    except Exception:
                        pass
                    await asyncio.sleep(0.5)
                if not ready:
                    bridge_log = await sandbox.commands.run("cat /opt/lda/codex-bridge.log 2>/dev/null || true")
                    raise RuntimeError(
                        "in-sandbox Codex protocol bridge did not become ready: "
                        + bridge_log.stdout[-1000:]
                    )
            config_lines: list[str] = []
            if spec.role == "builder":
                config_lines = [
                    "[mcp_servers.lda]",
                    'command = "lda-mcp"',
                ]
            if provider:
                config_lines = [
                    'model_provider = "factlab"',
                    "",
                    "[model_providers.factlab]",
                    'name = "Fact Lab Gateway"',
                    'base_url = "http://127.0.0.1:8787/v1"',
                    'env_key = "LDA_CODEX_API_KEY"',
                    'wire_api = "responses"',
                    "",
                    *config_lines,
                ]
            created = await sandbox.commands.run("mkdir -p /home/agent/.codex")
            if created.exit_code != 0:
                raise RuntimeError("could not create Agent Runtime Codex home")
            await sandbox.files.write(
                "/home/agent/.codex/config.toml",
                "\n".join(config_lines) + "\n",
            )
            if spec.backend in {"codex-sdk", "codex-cli"} and provider is None:
                if not self.codex_auth_path.is_file():
                    raise RuntimeError("controller has no injected Codex authentication")
                await sandbox.files.write(
                    "/home/agent/.codex/auth.json",
                    self.codex_auth_path.read_bytes(),
                )
                protected = await sandbox.commands.run("chmod 0600 /home/agent/.codex/auth.json")
                if protected.exit_code != 0:
                    raise RuntimeError("could not protect Agent Runtime Codex authentication")
        except Exception:
            self._bridge_processes.pop(lease.lease_id, None)
            await self.manager.kill(lease.lease_id)
            self._session_semaphore.release()
            raise
        token = self.authority.issue(
            run_id=spec.run_id,
            mission_id=spec.mission_id,
            candidate_id=spec.candidate_id,
            role=spec.role,
            workspace_id=spec.workspace_id,
            allowed_tools=spec.allowed_tools,
        )
        backend = self.backends.get(spec.backend)
        if backend is None:
            raise RuntimeError(f"agent backend is unavailable: {spec.backend}")
        return AgentHandle(
            spec,
            sandbox,
            lease,
            backend,
            token,
            self.artifacts,
            self.store,
            self.manager,
            self._session_semaphore,
        )

    @staticmethod
    def _validate_independence(spec: AgentSpec) -> None:
        if spec.role in {"reviewer", "trace-auditor"}:
            if spec.session_policy is not SessionPolicy.FRESH:
                raise ValueError(f"{spec.role} must use a fresh session")
            forbidden = {"workspace.write", "workspace.apply_patch", "workspace.exec"}
            if forbidden.intersection(spec.allowed_tools):
                raise PermissionError(f"{spec.role} cannot modify candidate source")
        if spec.role == "builder" and spec.session_policy is not SessionPolicy.PERSISTENT:
            raise ValueError("builder must use a persistent candidate thread")
