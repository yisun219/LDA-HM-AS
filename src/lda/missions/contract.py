from __future__ import annotations

from pathlib import PurePosixPath

from lda.models import MissionContract, stable_digest


PROTECTED_PATHS = (
    "/opt/lda/contracts",
    "/opt/lda/baseline",
    "/opt/lda/judge",
    "/opt/lda/tests",
    "/opt/lda/benchmarks",
)


def create_contract(**values) -> MissionContract:
    forbidden = list(dict.fromkeys([*values.get("forbidden_paths", []), *PROTECTED_PATHS]))
    values["forbidden_paths"] = forbidden
    allowed = values.get("allowed_source_paths", [])
    if not allowed:
        raise ValueError("mission contract must name writable source paths")
    for path in allowed:
        candidate = PurePosixPath(path)
        if not candidate.is_absolute() or any(str(candidate).startswith(item) for item in PROTECTED_PATHS):
            raise ValueError(f"invalid allowed source path: {path}")
    return MissionContract.model_validate(values)


def verify_contract(contract: MissionContract) -> None:
    expected = stable_digest(contract.model_dump(exclude={"contract_hash"}))
    if expected != contract.contract_hash:
        raise ValueError("mission contract has been modified")
