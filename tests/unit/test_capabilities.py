from datetime import timedelta

import pytest

from lda.gateway import CapabilityAuthority


def test_capability_is_scoped() -> None:
    authority = CapabilityAuthority(b"x" * 32)
    token = authority.issue(
        run_id="run",
        mission_id="mission",
        candidate_id="candidate",
        role="builder",
        workspace_id="workspace",
        allowed_tools=["workspace.read", "workspace.exec"],
        lifetime=timedelta(minutes=1),
    )
    capability = authority.verify(token)
    assert capability.permits("workspace.exec", run_id="run", mission_id="mission", candidate_id="candidate")
    assert not capability.permits("judge.accept", run_id="run", mission_id="mission", candidate_id="candidate")


def test_reviewer_cannot_request_write() -> None:
    authority = CapabilityAuthority(b"x" * 32)
    with pytest.raises(PermissionError):
        authority.issue(
            run_id="run",
            mission_id="mission",
            candidate_id="candidate",
            role="reviewer",
            workspace_id=None,
            allowed_tools=["workspace.write"],
        )
