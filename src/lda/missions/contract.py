from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

from lda.models import new_id, stable_hash, utc_now


@dataclass(frozen=True)
class MissionContract:
    mission_id: str
    package: str
    baseline_ref: str
    fence_version: str
    acceptance: dict[str, Any]
    created_at: str
    contract_hash: str

    @classmethod
    def create(cls, package: str, baseline_ref: str = "official-baseline", fence_version: str = "1"):
        body = {"mission_id": new_id("mission"), "package": package, "baseline_ref": baseline_ref,
                "fence_version": fence_version, "acceptance": {"clean_judge": True, "micro": 1.03,
                "e2e_regression_max": 0.005}, "created_at": utc_now()}
        return cls(**body, contract_hash=stable_hash(body))

    def dump(self) -> dict[str, Any]:
        return asdict(self)

