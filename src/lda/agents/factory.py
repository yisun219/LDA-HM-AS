from __future__ import annotations

import os
import shlex
from dataclasses import dataclass

from lda.e2b.client import E2BClient, Sandbox
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
    def __init__(self, client: E2BClient):
        self.client = client
        self.sessions: dict[str, str] = {}
        self.sandboxes: dict[str, Sandbox] = {}

    def spec(self, **kwargs) -> AgentSpec:
        role = kwargs["role"]
        return AgentSpec(runtime_template=RUNTIME_TEMPLATE,
                          session_policy=THREAD_POLICIES.get(role, "fresh"),
                          backend=kwargs.get("backend", "codex"), model=kwargs.get("model", "gpt-5"),
                          reasoning_effort=kwargs.get("reasoning_effort", "high"),
                          prompt_version=kwargs.get("prompt_version", "lda-v1"),
                          context_refs=kwargs.get("context_refs", []), allowed_tools=kwargs.get("allowed_tools", []),
                          workspace_id=kwargs.get("workspace_id"), output_schema=kwargs.get("output_schema", "manager_action"),
                          timeout_seconds=kwargs.get("timeout_seconds", 1800), token_budget=kwargs.get("token_budget", 10000),
                          independence_group=kwargs.get("independence_group", role), run_id=kwargs["run_id"],
                          life_cycle_id=kwargs.get("life_cycle_id"), mission_id=kwargs.get("mission_id"),
                          candidate_id=kwargs.get("candidate_id"), capability_id=kwargs.get("capability_id"), role=role)

    def create(self, spec: AgentSpec) -> tuple[AgentSpec, Sandbox]:
        lease = new_id("lease")
        sandbox = self.client.create({"project": "lda", "run_id": spec.run_id,
            "life_cycle": spec.life_cycle_id or "none", "mission_id": spec.mission_id or "none",
            "candidate_id": spec.candidate_id or "none", "capability_id": spec.capability_id or "none",
            "role": spec.role, "template": spec.runtime_template, "lease_id": lease})
        session_key = f"{spec.role}:{spec.independence_group}:{spec.candidate_id or spec.life_cycle_id or spec.run_id}"
        if spec.session_policy in {"candidate_persistent", "capability_persistent"}:
            self.sessions.setdefault(session_key, "thread_" + new_id("session"))
        else:
            self.sessions[session_key] = "thread_" + new_id("session")
        self.sandboxes[session_key] = sandbox
        return spec, sandbox

    def run(self, spec: AgentSpec, prompt: str) -> dict:
        """Run Codex inside the scoped runtime sandbox, never on the controller host."""
        key = f"{spec.role}:{spec.independence_group}:{spec.candidate_id or spec.life_cycle_id or spec.run_id}"
        sandbox = self.sandboxes.get(key)
        if sandbox is None:
            _, sandbox = self.create(spec)
        command = self.client.codex_command(prompt)
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
        return {"session_id": self.sessions[key], "role": spec.role, "result": result}

    def release(self, spec: AgentSpec) -> None:
        key = f"{spec.role}:{spec.independence_group}:{spec.candidate_id or spec.life_cycle_id or spec.run_id}"
        sandbox = self.sandboxes.get(key)
        if sandbox is not None and sandbox.alive:
            self.client.kill(sandbox)
