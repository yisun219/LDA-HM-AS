from __future__ import annotations

import hashlib
import json
import re
from pathlib import PurePosixPath
from typing import Any

from lda.agents.factory import AgentFactory
from lda.argus.capabilities.registry import CapabilityRegistry
from lda.artifacts.store import ArtifactStore
from lda.models import Capability, WorldState, new_id


class CapabilityExecutor:
    """Build and independently judge one capability in scoped E2B sandboxes."""

    FORBIDDEN_COMMANDS = re.compile(
        r"(^|[;&|\s])(curl|wget|git|apt|apt-get|sudo|mount|sysctl|taskset|chrt)([;&|\s]|$)"
    )

    def __init__(self, world: WorldState, agents: AgentFactory, registry: CapabilityRegistry,
                 artifacts: ArtifactStore):
        self.world = world
        self.agents = agents
        self.registry = registry
        self.artifacts = artifacts

    @staticmethod
    def _safe_files(raw: Any) -> dict[str, bytes]:
        if not isinstance(raw, dict) or not raw:
            raise ValueError("Capability Builder must return at least one file")
        files: dict[str, bytes] = {}
        total = 0
        for name, content in raw.items():
            path = PurePosixPath(str(name))
            if path.is_absolute() or ".." in path.parts or not path.parts:
                raise ValueError(f"capability file path escapes workspace: {name}")
            if not isinstance(content, str):
                raise ValueError(f"capability file is not text: {name}")
            payload = content.encode()
            total += len(payload)
            if total > 1_000_000:
                raise ValueError("capability payload exceeds 1 MB")
            files[str(path)] = payload
        return files

    @classmethod
    def _safe_test_command(cls, command: Any) -> str:
        if not isinstance(command, str) or not command.strip():
            raise ValueError("capability test command is missing")
        if len(command) > 2000 or cls.FORBIDDEN_COMMANDS.search(command):
            raise ValueError("capability test command violates isolated policy")
        return command.strip()

    def _reject(self, capability: Capability, reason: str) -> dict[str, Any]:
        capability.failure_reason = reason
        if capability.status not in self.registry.TERMINAL:
            self.registry.transition(capability, "REJECTED")
        return {"capability_id": capability.capability_id, "status": capability.status,
                "passed": False, "reason": reason}

    def run(self, capability: Capability) -> dict[str, Any]:
        work = None
        judge = None
        builder = None
        reviewer = None
        try:
            if capability.status == "PROPOSED":
                self.registry.transition(capability, "POLICY_APPROVED")
            if capability.status == "POLICY_APPROVED":
                self.registry.transition(capability, "BUILDING")
            if capability.status != "BUILDING":
                return self._reject(capability, "capability must enter executor in BUILDING state")

            metadata = {"project": "lda", "run_id": self.world.run_id,
                "life_cycle": str(self.world.life_cycle), "mission_id": "capability",
                "candidate_id": "none", "capability_id": capability.capability_id,
                "role": "capability-work", "template": "lda-base-lda-hm-as-prod-20260825-v12",
                "lease_id": new_id("lease")}
            work = self.agents.client.create(metadata)
            builder = self.agents.spec(
                run_id=self.world.run_id, life_cycle_id=str(self.world.life_cycle),
                capability_id=capability.capability_id, role="Capability Builder",
                independence_group="capability-builder", timeout_seconds=900)
            self.agents.create(builder)
            build_result = self.agents.run(
                builder,
                "Build a scoped, versioned LDA capability. Return files and a deterministic offline test "
                "command only. Do not download, modify Fence, access secrets, alter Judge, or write outside "
                f"the capability workspace. kind={capability.kind}; scope={capability.scope}; "
                f"version={capability.version}; proposal_hash={capability.content_hash}")
            output = build_result.get("output")
            if not isinstance(output, dict):
                return self._reject(capability, "Capability Builder returned no schema-valid output")
            try:
                files = self._safe_files(output.get("files"))
                test_command = self._safe_test_command(output.get("test_command"))
            except ValueError as exc:
                return self._reject(capability, str(exc))

            root = f"/workspace/capabilities/{capability.capability_id}"
            for name, payload in files.items():
                self.agents.client.filesystem_write(work, f"{root}/{name}", payload)
                capability.artifact_refs[name] = self.artifacts.put(name, payload)
            test = self.agents.client.command_checkpointed(
                work, f"cd {root} && {test_command}", timeout=900)
            capability.evidence_refs.extend(capability.artifact_refs.values())
            if test.get("exit_code") != 0:
                return self._reject(capability, "isolated capability tests failed")
            self.registry.transition(capability, "ISOLATED_TEST", tests_passed=True)

            reviewer = self.agents.spec(
                run_id=self.world.run_id, life_cycle_id=str(self.world.life_cycle),
                capability_id=capability.capability_id, role="Reviewer",
                independence_group="capability-reviewer", timeout_seconds=300)
            self.agents.create(reviewer)
            review = self.agents.run(
                reviewer,
                "Review this capability independently. Reject scope escape, hidden network, Fence/Judge "
                "changes, missing failure behavior, or tests that do not exercise the entrypoint. Return JSON. "
                + json.dumps({"kind": capability.kind, "scope": capability.scope,
                              "files": {name: hashlib.sha256(payload).hexdigest()
                                        for name, payload in files.items()},
                              "entrypoint": output.get("entrypoint"),
                              "failure_mode": output.get("failure_mode"),
                              "test_exit_code": test.get("exit_code")}, sort_keys=True))
            review_output = review.get("output")
            if not isinstance(review_output, dict) or review_output.get("verdict") != "APPROVE":
                return self._reject(capability, "independent capability review did not approve")
            self.registry.transition(capability, "ADVERSARIAL_REVIEW")
            self.registry.transition(capability, "CAPABILITY_JUDGE")

            judge = self.agents.client.create({**metadata, "role": "capability-judge",
                                                "lease_id": new_id("lease")})
            judge_root = f"/workspace/capability-judge/{capability.capability_id}"
            for name, ref in capability.artifact_refs.items():
                self.agents.client.filesystem_write(judge, f"{judge_root}/{name}", self.artifacts.get(ref))
            secret_probe = self.agents.client.command(
                judge,
                "env | grep -E '^(E2B_API_KEY|OPENAI_API_KEY|CODEX_API_KEY|OPENAI_BASE_URL)='",
                timeout=30)
            judge_test = self.agents.client.command_checkpointed(
                judge, f"cd {judge_root} && {test_command}", timeout=900)
            hashes_match = all(
                hashlib.sha256(self.artifacts.get(ref)).hexdigest() ==
                hashlib.sha256(files[name]).hexdigest()
                for name, ref in capability.artifact_refs.items())
            passed = secret_probe.get("exit_code") != 0 and judge_test.get("exit_code") == 0 and hashes_match
            if not passed:
                return self._reject(capability, "Capability Judge rejected isolated artifact")
            self.registry.transition(capability, "ACTIVE", judge_passed=True)
            return {"capability_id": capability.capability_id, "status": capability.status,
                    "passed": True, "artifact_refs": dict(capability.artifact_refs),
                    "test_exit_code": test.get("exit_code"),
                    "judge_exit_code": judge_test.get("exit_code")}
        except Exception as exc:
            return self._reject(capability, f"capability execution failed: {exc}")
        finally:
            for sandbox in (work, judge):
                if sandbox is not None and sandbox.alive:
                    self.agents.client.kill(sandbox)
            for spec in (reviewer, builder):
                if spec is not None:
                    self.agents.release(spec)
