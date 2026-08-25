from __future__ import annotations

from dataclasses import dataclass

from lda.agents.factory import AgentFactory
from lda.models import AgentSpec


@dataclass
class CodexSession:
    thread_id: str
    independence_group: str
    resumed: bool = False


class CodexRuntime:
    """Backend boundary for the OpenAI Codex SDK or CLI fallback."""

    def __init__(self, factory: AgentFactory):
        self.factory = factory

    def start(self, spec: AgentSpec) -> CodexSession:
        self.factory.create(spec)
        key = f"{spec.role}:{spec.independence_group}:{spec.candidate_id or spec.life_cycle_id or spec.run_id}"
        return CodexSession(self.factory.sessions[key], spec.independence_group)

    def resume_builder(self, spec: AgentSpec) -> CodexSession:
        session = self.start(spec)
        session.resumed = True
        return session

