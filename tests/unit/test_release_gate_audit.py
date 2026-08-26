import unittest

from lda.argus.policy.engine import PolicyEngine, PolicyViolation
from lda.models import ManagerAction, WorldState


class ReleaseGateAuditTest(unittest.TestCase):
    def test_empty_qualification_set_does_not_authorize_dynamic_mission(self):
        action = ManagerAction(
            "CREATE_MISSION",
            target_id="unverified-package",
            evidence_refs=["research-report"],
            estimated_cost=1.0,
        )
        with self.assertRaisesRegex(PolicyViolation, "not qualified"):
            PolicyEngine().validate(action, WorldState("r"))


if __name__ == "__main__":
    unittest.main()
