from pathlib import Path

import pytest

from lda.agents import AgentFactory, FakeCodexBackend
from lda.agents.factory import CodexCliBackend
from lda.artifacts import ArtifactStore
from lda.gateway import CapabilityAuthority
from lda.models import AgentSpec, SessionPolicy
from lda.state import EventStore

from .fakes import FakeSandbox


class Manager:
    def __init__(self) -> None:
        self.sandboxes = []

    async def create(self, lease, **kwargs):
        sandbox = FakeSandbox(f"agent-{len(self.sandboxes)}")
        self.sandboxes.append(sandbox)
        return sandbox

    async def kill(self, lease_id):
        return None


def spec(role: str, schema: str, *, candidate: str | None, policy: SessionPolicy) -> AgentSpec:
    tools = ["workspace.read"] if role == "builder" else ["artifact.read"]
    return AgentSpec(
        run_id="run",
        mission_id="mission",
        candidate_id=candidate,
        role=role,
        backend="fake",
        model="fake",
        reasoning_effort="high",
        prompt_version="v1",
        allowed_tools=tools,
        session_policy=policy,
        output_schema=schema,
        timeout_seconds=60,
        token_budget=100,
        independence_group=f"{role}-group",
    )


async def test_builder_resume_and_reviewer_independence(tmp_path: Path) -> None:
    artifacts = ArtifactStore(tmp_path / "artifacts")
    prompt = artifacts.put_bytes(b"prompt")
    schema = artifacts.put_json({"type": "object"})
    auth = tmp_path / "auth.json"
    auth.write_text("{}", encoding="utf-8")
    auth.chmod(0o600)
    backend = FakeCodexBackend([{"turn": 1}, {"turn": 2}, {"review": True}])
    factory = AgentFactory(
        Manager(),
        artifacts,
        EventStore(tmp_path / "state"),
        CapabilityAuthority(b"x" * 32),
        gateway_url="https://gateway",
        codex_auth_path=auth,
        backends={"fake": backend},
    )
    builder = await factory.spawn(spec("builder", schema, candidate="candidate", policy=SessionPolicy.PERSISTENT))
    first = await builder.run(prompt)
    second = await builder.resume(prompt)
    assert first.thread_id == second.thread_id
    reviewer = await factory.spawn(spec("reviewer", schema, candidate="candidate", policy=SessionPolicy.FRESH))
    reviewed = await reviewer.run(prompt)
    assert reviewed.thread_id != first.thread_id
    with pytest.raises(RuntimeError):
        await reviewer.resume(prompt)


def test_reviewer_policy_is_enforced(tmp_path: Path) -> None:
    with pytest.raises(ValueError):
        AgentFactory._validate_independence(
            spec("reviewer", "schema", candidate="candidate", policy=SessionPolicy.PERSISTENT)
        )


async def test_cli_backend_ignores_non_json_trace_lines(tmp_path: Path) -> None:
    sandbox = FakeSandbox("agent")
    original_run = sandbox.commands.run

    async def run(command, **kwargs):
        result = await original_run(command, **kwargs)
        if "command-state" in command:
            roots = [path.rsplit("/", 1)[0] for path in sandbox.files.values if path.endswith("/schema.json")]
            root = roots[0]
            sandbox.files.values[f"{root}/output.json"] = b'{"ok":true}'
            sandbox.files.values[f"{root}/trace.jsonl"] = (
                b"diagnostic text\n\n"
                b'{"type":"thread.started","thread_id":"thread-1"}\n'
            )
        return result

    sandbox.commands.run = run
    result = await CodexCliBackend().run(
        sandbox,
        spec("research-curator", "unused", candidate=None, policy=SessionPolicy.FRESH),
        prompt="prompt",
        schema={"type": "object"},
        thread_id=None,
        capability_token="token",
    )
    assert result.thread_id == "thread-1"
    assert result.output == {"ok": True}


async def test_cli_backend_retries_malformed_structured_output(tmp_path: Path) -> None:
    sandbox = FakeSandbox("agent")
    original_run = sandbox.commands.run
    attempts = 0

    async def run(command, **kwargs):
        nonlocal attempts
        result = await original_run(command, **kwargs)
        if "command-state" in command:
            attempts += 1
            roots = [path.rsplit("/", 1)[0] for path in sandbox.files.values if path.endswith("/schema.json")]
            root = roots[0]
            output = b"not-json" if attempts == 1 else b'{"ok":true}'
            sandbox.files.values[f"{root}/output.json"] = output
            sandbox.files.values[f"{root}/trace.jsonl"] = b'{"type":"thread.started","thread_id":"thread-2"}\n'
        return result

    sandbox.commands.run = run
    result = await CodexCliBackend().run(
        sandbox,
        spec("research-curator", "unused", candidate=None, policy=SessionPolicy.FRESH),
        prompt="prompt",
        schema={"type": "object"},
        thread_id=None,
        capability_token="token",
    )
    assert attempts == 2
    assert result.output == {"ok": True}


async def test_cli_backend_retries_schema_invalid_json(tmp_path: Path) -> None:
    sandbox = FakeSandbox("agent")
    original_run = sandbox.commands.run
    attempts = 0

    async def run(command, **kwargs):
        nonlocal attempts
        result = await original_run(command, **kwargs)
        if "command-state" in command:
            attempts += 1
            root = next(path.rsplit("/", 1)[0] for path in sandbox.files.values if path.endswith("/schema.json"))
            sandbox.files.values[f"{root}/output.json"] = b"{}" if attempts == 1 else b'{"ok":true}'
            sandbox.files.values[f"{root}/trace.jsonl"] = b'{"type":"thread.started","thread_id":"thread-3"}\n'
        return result

    sandbox.commands.run = run
    result = await CodexCliBackend().run(
        sandbox,
        spec("research-curator", "unused", candidate=None, policy=SessionPolicy.FRESH),
        prompt="prompt",
        schema={"type": "object", "required": ["ok"], "properties": {"ok": {"type": "boolean"}}},
        thread_id=None,
        capability_token="token",
    )
    assert attempts == 2
    assert result.output == {"ok": True}
