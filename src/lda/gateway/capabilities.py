from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
from datetime import datetime, timedelta, timezone
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


ROLE_TOOLS = {
    "builder": frozenset(
        {
            "workspace.read",
            "workspace.write",
            "workspace.apply_patch",
            "workspace.exec",
            "workspace.profile",
            "workspace.git_diff",
            "artifact.publish",
        }
    ),
    "reviewer": frozenset(
        {
            "artifact.read",
            "candidate.diff",
            "test_result.read",
            "benchmark_result.read",
            "trace.read",
        }
    ),
    "trace-auditor": frozenset({"candidate.diff", "trace.read", "artifact.read"}),
    "research-curator": frozenset({"artifact.read"}),
    "portfolio-planner": frozenset({"artifact.read"}),
    "mission-planner": frozenset({"artifact.read", "test_result.read", "benchmark_result.read"}),
    "profiler": frozenset({"artifact.read", "test_result.read", "benchmark_result.read"}),
}
FORBIDDEN_TOOLS = frozenset(
    {
        "judge.accept",
        "baseline.modify",
        "test_manifest.modify",
        "secret.read",
        "sandbox.create_unscoped",
        "release.publish",
    }
)


class Capability(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    run_id: str
    mission_id: str
    candidate_id: str | None
    role: str
    workspace_id: str | None
    allowed_tools: list[str]
    issued_at: datetime
    expires_at: datetime
    nonce: str

    def permits(self, tool: str, *, run_id: str, mission_id: str, candidate_id: str | None) -> bool:
        now = datetime.now(timezone.utc)
        return (
            now < self.expires_at
            and tool in self.allowed_tools
            and tool not in FORBIDDEN_TOOLS
            and self.run_id == run_id
            and self.mission_id == mission_id
            and self.candidate_id == candidate_id
        )


class CapabilityAuthority:
    def __init__(self, secret: bytes) -> None:
        if len(secret) < 32:
            raise ValueError("capability signing key must be at least 32 bytes")
        self.secret = secret

    @classmethod
    def from_environment(cls, name: str = "LDA_CAPABILITY_SIGNING_KEY") -> "CapabilityAuthority":
        value = os.getenv(name, "")
        if not value:
            raise RuntimeError(f"{name} is required in lda-controller")
        return cls(value.encode())

    def issue(
        self,
        *,
        run_id: str,
        mission_id: str,
        candidate_id: str | None,
        role: str,
        workspace_id: str | None,
        allowed_tools: list[str],
        lifetime: timedelta = timedelta(minutes=20),
    ) -> str:
        role_tools = ROLE_TOOLS.get(role)
        if role_tools is None:
            raise ValueError(f"unknown capability role: {role}")
        requested = set(allowed_tools)
        if requested - role_tools or requested & FORBIDDEN_TOOLS:
            raise PermissionError(f"role {role} requested forbidden tools")
        now = datetime.now(timezone.utc)
        capability = Capability(
            run_id=run_id,
            mission_id=mission_id,
            candidate_id=candidate_id,
            role=role,
            workspace_id=workspace_id,
            allowed_tools=sorted(requested),
            issued_at=now,
            expires_at=now + lifetime,
            nonce=os.urandom(16).hex(),
        )
        payload = capability.model_dump_json().encode()
        signature = hmac.new(self.secret, payload, hashlib.sha256).digest()
        return f"{_encode(payload)}.{_encode(signature)}"

    def verify(self, token: str) -> Capability:
        try:
            encoded_payload, encoded_signature = token.split(".", 1)
            payload = _decode(encoded_payload)
            signature = _decode(encoded_signature)
        except Exception as error:
            raise PermissionError("invalid capability token") from error
        expected = hmac.new(self.secret, payload, hashlib.sha256).digest()
        if not hmac.compare_digest(signature, expected):
            raise PermissionError("invalid capability signature")
        capability = Capability.model_validate(json.loads(payload))
        if datetime.now(timezone.utc) >= capability.expires_at:
            raise PermissionError("capability token expired")
        return capability


def _encode(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode()


def _decode(value: str) -> bytes:
    return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))
