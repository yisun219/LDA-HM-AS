from __future__ import annotations

import json
import os

from lda.e2b.client import E2BClient, Sandbox
from lda.agents.outputs import ROLE_SCHEMAS, schema_for
from lda.models import AgentSpec, new_id


ROLE_TEMPLATES = {
    "Argus Manager": "lda-agent-runtime", "World State Summarizer": "lda-agent-runtime",
    "Research Curator": "lda-agent-runtime", "Mission Planner": "lda-agent-runtime",
    "Profiler": "lda-agent-runtime", "Builder": "lda-agent-runtime", "Reviewer": "lda-agent-runtime",
    "Trace Auditor": "lda-agent-runtime", "Outcome Classifier": "lda-agent-runtime",
    "Capability Planner": "lda-agent-runtime", "Capability Builder": "lda-agent-runtime",
}
RUNTIME_TEMPLATE = os.environ.get("LDA_AGENT_RUNTIME_TEMPLATE", "lda-production-2604-v10")
THREAD_POLICIES = {"Argus Manager": "new_life_cycle", "World State Summarizer": "new_cycle",
                   "Mission Planner": "new_mission", "Builder": "candidate_persistent",
                   "Reviewer": "fresh_round", "Outcome Classifier": "new_outcome",
                   "Capability Builder": "capability_persistent"}


class AgentFactory:
    def __init__(self, client: E2BClient, session_state: dict[str, dict] | None = None):
        self.client = client
        self.session_state = session_state if session_state is not None else {}
        self.sessions: dict[str, str] = {
            key: value["session_id"] for key, value in self.session_state.items()
            if isinstance(value, dict) and isinstance(value.get("session_id"), str)
        }
        self.sandboxes: dict[str, Sandbox] = {}

    def spec(self, **kwargs) -> AgentSpec:
        role = kwargs["role"]
        return AgentSpec(runtime_template=RUNTIME_TEMPLATE,
                          session_policy=THREAD_POLICIES.get(role, "fresh"),
                          backend=kwargs.get("backend", "codex"), model=kwargs.get("model", "gpt-5"),
                          reasoning_effort=kwargs.get("reasoning_effort", "high"),
                          prompt_version=kwargs.get("prompt_version", "lda-v1"),
                          context_refs=kwargs.get("context_refs", []), allowed_tools=kwargs.get("allowed_tools", []),
                          workspace_id=kwargs.get("workspace_id"),
                          output_schema=kwargs.get("output_schema", ROLE_SCHEMAS.get(role, "world_summary")),
                          timeout_seconds=kwargs.get("timeout_seconds", 1800), token_budget=kwargs.get("token_budget", 10000),
                          independence_group=kwargs.get("independence_group", role), run_id=kwargs["run_id"],
                          life_cycle_id=kwargs.get("life_cycle_id"), mission_id=kwargs.get("mission_id"),
                          candidate_id=kwargs.get("candidate_id"), capability_id=kwargs.get("capability_id"), role=role)

    def create(self, spec: AgentSpec) -> tuple[AgentSpec, Sandbox]:
        session_key = f"{spec.role}:{spec.independence_group}:{spec.candidate_id or spec.life_cycle_id or spec.run_id}"
        persistent = spec.session_policy in {"candidate_persistent", "capability_persistent"}
        existing = self.sandboxes.get(session_key)
        if persistent and existing is not None and existing.alive:
            return spec, existing
        recovered = self.session_state.get(session_key, {}) if persistent else {}
        recovered_id = recovered.get("sandbox_id") if isinstance(recovered, dict) else None
        if recovered_id and recovered.get("active") is True:
            try:
                sandbox = self.client.connect(recovered_id)
                sandbox.metadata.update(recovered.get("metadata", {}))
                self.sandboxes[session_key] = sandbox
                return spec, sandbox
            except RuntimeError:
                recovered["active"] = False
        lease = new_id("lease")
        metadata = {"project": "lda", "run_id": spec.run_id,
            "life_cycle": spec.life_cycle_id or "none", "mission_id": spec.mission_id or "none",
            "candidate_id": spec.candidate_id or "none", "capability_id": spec.capability_id or "none",
            "role": spec.role, "template": spec.runtime_template, "lease_id": lease,
            "timeout": 86400 if persistent else max(3600, spec.timeout_seconds + 300)}
        sandbox = self.client.create(metadata)
        if not persistent:
            self.sessions.pop(session_key, None)
        else:
            self.session_state[session_key] = {
                "sandbox_id": sandbox.sandbox_id, "session_id": self.sessions.get(session_key),
                "active": True, "session_policy": spec.session_policy, "metadata": metadata,
            }
        self.sandboxes[session_key] = sandbox
        return spec, sandbox

    @staticmethod
    def _thread_id(stdout: str) -> str | None:
        for line in stdout.splitlines():
            try:
                event = json.loads(line)
            except (TypeError, ValueError, json.JSONDecodeError):
                continue
            if not isinstance(event, dict):
                continue
            for key in ("thread_id", "session_id", "conversation_id"):
                value = event.get(key)
                if isinstance(value, str) and value:
                    return value
            nested = event.get("thread")
            if isinstance(nested, dict) and isinstance(nested.get("id"), str):
                return nested["id"]
        return None

    @staticmethod
    def _final_output(stdout: str) -> dict | None:
        messages: list[str] = []
        for line in stdout.splitlines():
            try:
                event = json.loads(line)
            except (TypeError, ValueError, json.JSONDecodeError):
                continue
            item = event.get("item") if isinstance(event, dict) else None
            if isinstance(item, dict) and item.get("type") == "agent_message" and isinstance(item.get("text"), str):
                messages.append(item["text"])
        if not messages:
            return None
        try:
            value = json.loads(messages[-1])
            return value if isinstance(value, dict) else None
        except (TypeError, ValueError, json.JSONDecodeError):
            return None

    def run(self, spec: AgentSpec, prompt: str) -> dict:
        """Run Codex inside the scoped runtime sandbox, never on the controller host."""
        key = f"{spec.role}:{spec.independence_group}:{spec.candidate_id or spec.life_cycle_id or spec.run_id}"
        sandbox = self.sandboxes.get(key)
        if sandbox is None:
            _, sandbox = self.create(spec)
        persistent = spec.session_policy in {"candidate_persistent", "capability_persistent"}
        prior_session = self.sessions.get(key) if persistent else None
        schema_path = f"/workspace/lda/schemas/{spec.output_schema}.json"
        self.client.filesystem_write(sandbox, schema_path,
                                     json.dumps(schema_for(spec.output_schema), sort_keys=True))
        command = self.client.codex_command(prompt, session_id=prior_session,
                                            model=spec.model, reasoning_effort=spec.reasoning_effort,
                                            output_schema_path=schema_path)
        try:
            # The gateway's default command deadline is short.  AgentSpec is
            # the authoritative bounded lifetime for a Codex session; without
            # forwarding it real Builder/Reviewer sessions are killed at the
            # transport default before they can return structured JSON.
            result = self.client.command(sandbox, command, background=False,
                                         timeout=spec.timeout_seconds)
        except Exception as exc:
            if self.client.allow_agent_stub and os.environ.get("LDA_ALLOW_AGENT_STUB") == "1":
                result = {"status": "agent_stub", "exit_code": 0, "stdout": "{}", "stderr": str(exc)}
            else:
                raise
        observed_session = self._thread_id(result.get("stdout", ""))
        if observed_session:
            self.sessions[key] = observed_session
            if persistent:
                self.session_state.setdefault(key, {})["session_id"] = observed_session
        return {"session_id": self.sessions.get(key), "resumed": bool(prior_session),
                "role": spec.role, "output": self._final_output(result.get("stdout", "")),
                "result": result}

    def release(self, spec: AgentSpec) -> None:
        key = f"{spec.role}:{spec.independence_group}:{spec.candidate_id or spec.life_cycle_id or spec.run_id}"
        sandbox = self.sandboxes.get(key)
        if sandbox is not None and sandbox.alive:
            self.client.kill(sandbox)
        self.sandboxes.pop(key, None)
        if key in self.session_state:
            self.session_state[key]["active"] = False
