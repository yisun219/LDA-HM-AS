from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

from .sandbox import Sandbox, SandboxResult
from .task_card import TaskCard


@dataclass(frozen=True)
class FenceResult:
    name: str
    passed: bool
    reason: str
    command_results: tuple[SandboxResult, ...] = ()


class FenceSuite:
    """Deterministic boundary checks run before semantic Reviewer access."""

    def __init__(
        self,
        sandbox: Sandbox,
        card: TaskCard,
        *,
        trace_file: Path | None = None,
        trace_remote: str | None = None,
    ) -> None:
        self.sandbox = sandbox
        self.card = card
        self.trace_file = trace_file
        self.trace_remote = trace_remote

    def run(self) -> tuple[FenceResult, ...]:
        checks: list[FenceResult] = []
        checks.extend(self._commands("baseline_tests", self.card.baseline_tests))
        checks.extend(self._commands("dependency_tests", self.card.dependency_tests))
        checks.extend(self._commands("abi_checks", self.card.abi_checks))
        checks.extend(self._commands("ffi_checks", self.card.ffi_checks))
        checks.extend(self._commands("behavior_checks", self.card.behavior_checks))
        checks.extend(self._commands("package_lifecycle_checks", self.card.package_lifecycle_checks))
        checks.extend(self._commands("security_checks", self.card.security_checks))
        checks.extend(self._commands("result_equivalence_checks", self.card.result_equivalence_checks))
        checks.append(self._trace_fence())
        return tuple(checks)

    @property
    def passed(self) -> bool:
        return all(result.passed for result in self.run())

    def _commands(self, name: str, commands: Iterable[tuple[str, ...]]) -> list[FenceResult]:
        results: list[FenceResult] = []
        for command in commands:
            result = self.sandbox.run(command)
            results.append(FenceResult(name, result.ok, self._command_reason(result), (result,)))
            if not result.ok:
                break
        return results

    @staticmethod
    def _command_reason(result: SandboxResult) -> str:
        return "passed" if result.ok else f"exit={result.exit_code}: {result.stderr[-500:]}"

    def _trace_fence(self) -> FenceResult:
        if self.trace_remote is not None:
            result = self.sandbox.run(
                ("python3", "/opt/lda/harness/audit_trace.py", self.trace_remote)
            )
            return FenceResult(
                "builder_trace",
                result.ok,
                "passed" if result.ok else f"trace audit failed: {result.stderr[-500:]}",
                (result,),
            )
        if self.trace_file is None:
            return FenceResult("builder_trace", False, "builder trace is required")
        if not self.trace_file.is_file():
            return FenceResult("builder_trace", False, "builder trace is missing")
        try:
            events = [json.loads(line) for line in self.trace_file.read_text(encoding="utf-8").splitlines() if line.strip()]
        except (OSError, json.JSONDecodeError) as error:
            return FenceResult("builder_trace", False, f"invalid trace: {error}")
        allowed = {"prompt", "tool_call", "tool_result", "checkpoint", "stop", "review_request"}
        for event in events:
            if not isinstance(event, dict) or event.get("kind") not in allowed:
                return FenceResult("builder_trace", False, "trace contains an unknown event")
            if event.get("role") == "reviewer":
                return FenceResult("builder_trace", False, "builder trace impersonates reviewer")
            if event.get("cheat") is True or event.get("bypass_fence") is True:
                return FenceResult("builder_trace", False, "trace records a fence bypass")
        if not any(event.get("kind") == "stop" for event in events):
            return FenceResult("builder_trace", False, "builder stop event is missing")
        return FenceResult("builder_trace", True, f"validated {len(events)} events")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def parse_p_severity(lines: Iterable[str]) -> tuple[str, ...]:
    pattern = re.compile(r"^\[P([0-9])\]\s+(.+)$")
    return tuple(line.strip() for line in lines if pattern.match(line.strip()))
