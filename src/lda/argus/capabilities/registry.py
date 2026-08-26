from __future__ import annotations

from lda.models import Capability, WorldState, new_id, stable_hash


class CapabilityRegistry:
    ORDER = ("PROPOSED", "POLICY_APPROVED", "BUILDING", "ISOLATED_TEST", "ADVERSARIAL_REVIEW", "CAPABILITY_JUDGE", "ACTIVE", "REJECTED")
    TERMINAL = frozenset({"ACTIVE", "REJECTED"})

    def propose(self, world: WorldState, kind: str, version: str, scope: list[str], content: str) -> Capability:
        capability = Capability(new_id("cap"), kind, version, stable_hash(content), scope)
        world.capabilities.append(capability)
        return capability

    def transition(self, capability: Capability, status: str, *, tests_passed: bool = False, judge_passed: bool = False) -> None:
        if status not in self.ORDER:
            raise ValueError(f"invalid capability status: {status}")
        if capability.status in self.TERMINAL:
            raise ValueError("terminal capability status cannot transition")
        if status == capability.status:
            raise ValueError("capability lifecycle cannot repeat a status")
        if status != "REJECTED":
            current = self.ORDER.index(capability.status)
            expected = self.ORDER[current + 1]
            if status != expected:
                raise ValueError(f"capability lifecycle must transition to {expected}")
        if tests_passed and status != "ISOLATED_TEST":
            raise ValueError("isolated test evidence can only be recorded at ISOLATED_TEST")
        if status == "ISOLATED_TEST" and not tests_passed:
            raise ValueError("isolated tests must pass before adversarial review")
        if status in {"ADVERSARIAL_REVIEW", "CAPABILITY_JUDGE", "ACTIVE"} and not capability.tests_passed:
            raise ValueError("capability has no passing isolated test evidence")
        if judge_passed and status != "ACTIVE":
            raise ValueError("Capability Judge decision can only be recorded at activation")
        if status == "ACTIVE" and not judge_passed:
            raise ValueError("only a passing Capability Judge decision can activate a capability")
        capability.status = status
        capability.tests_passed = tests_passed or capability.tests_passed
        capability.judge_passed = judge_passed
