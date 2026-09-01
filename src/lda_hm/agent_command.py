from __future__ import annotations

import os
import shlex
import tempfile
from pathlib import Path

from .sandbox import Sandbox


class CommandSession:
    def __init__(self, sandbox: Sandbox, command: tuple[str, ...], *, role: str, session_id: str) -> None:
        self.sandbox = sandbox
        self.command = command
        self.role = role
        self.session_id = session_id
        self.turn = 0

    def ask(self, prompt: str, *, schema=None):
        self.turn += 1
        remote_tmp = os.getenv("LDA_REMOTE_TMPDIR", "/scratch/lda-hm")
        name = f"{remote_tmp}/lda-{self.role}-{self.session_id}-{self.turn}.prompt"
        # The E2B adapter owns file transport. Prompts never go through a host shell.
        local_tmp = os.getenv("TMPDIR", "/scratch/lda-hm")
        Path(local_tmp).mkdir(parents=True, exist_ok=True)
        local = Path(tempfile.mkstemp(prefix="lda-prompt-", dir=local_tmp)[1])
        try:
            local.write_text(prompt, encoding="utf-8")
            self.sandbox.put(local, name)
            command = self.command + ("--prompt-file", name, "--role", self.role, "--session", self.session_id)
            turn_timeout = int(os.getenv("LDA_TURN_TIMEOUT", "4200"))
            command = ("env", f"LDA_TURN_TIMEOUT={turn_timeout}") + command
            result = self.sandbox.run(command, timeout_seconds=2 * turn_timeout + 600)
            if not result.ok:
                raise RuntimeError(f"{self.role} agent failed with exit {result.exit_code}: {result.stderr[-1000:]}")
            return result.stdout.strip()
        finally:
            local.unlink(missing_ok=True)


class CommandAgent:
    """Agent adapter for an E2B-installed harness command.

    The command must accept `--prompt-file`, `--role`, and `--session`, and
    print one response to stdout. A session id is stable across turns; a fresh
    `new_session` call gets a different id for Analyst/Reviewer independence.
    """

    def __init__(self, sandbox: Sandbox, command: tuple[str, ...], *, role: str) -> None:
        if not command:
            raise ValueError("agent command must not be empty")
        self.sandbox = sandbox
        self.command = command
        self.role = role
        self._next = 0

    @classmethod
    def from_env(cls, sandbox: Sandbox, *, role: str) -> "CommandAgent":
        raw = os.getenv(
            "LDA_AGENT_COMMAND",
            "/opt/lda/harness/lda-agent-harness.sh",
        ).strip()
        return cls(sandbox, tuple(shlex.split(raw)), role=role)

    def new_session(self, cwd: Path) -> CommandSession:
        self._next += 1
        return CommandSession(self.sandbox, self.command, role=self.role, session_id=f"{self.role}-{self._next}")
