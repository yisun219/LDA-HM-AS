from __future__ import annotations

from lda.models import Capability, WorldState, new_id, stable_hash


class CapabilityRegistry:
    ORDER = ("PROPOSED", "POLICY_APPROVED", "BUILDING", "ISOLATED_TEST", "ADVERSARIAL_REVIEW", "CAPABILITY_JUDGE", "ACTIVE", "REJECTED")

    def propose(self, world: WorldState, kind: str, version: str, scope: list[str], content: str) -> Capability:
        capability = Capability(new_id("cap"), kind, version, stable_hash(content), scope)
        world.capabilities.append(capability)
        return capability

    def transition(self, capability: Capability, status: str, *, tests_passed: bool = False, judge_passed: bool = False) -> None:
        if status not in self.ORDER:
            raise ValueError(f"invalid capability status: {status}")
        old = self.ORDER.index(capability.status)
        new = self.ORDER.index(status)
        if status == "ACTIVE" and not (judge_passed or capability.judge_passed):
            raise ValueError("only Capability Judge can activate a capability")
        if status not in {"REJECTED", "ACTIVE"} and new < old:
            raise ValueError("capability lifecycle cannot move backwards")
        capability.status = status
        capability.tests_passed = tests_passed or capability.tests_passed
        capability.judge_passed = judge_passed or capability.judge_passed

