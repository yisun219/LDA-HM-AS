import json, tempfile, unittest
from pathlib import Path
from humanize import Humanize, FlowError, Verdict, Phase, GATES
class FlowTest(unittest.TestCase):
    def setUp(self): self.tmp=tempfile.TemporaryDirectory(); self.root=Path(self.tmp.name); self.h=Humanize.init(self.root,'goal','LDA-HM-AS')
    def tearDown(self): self.tmp.cleanup()
    def plan(self):
        self.h.idea(['a','b'],'a'); self.h.plan({'objective':'o','acceptance_criteria':['ac'],'positive_tests':['p'],'negative_tests':['n'],'path_boundaries':['src']},True)
    def test_sessions_and_anchor_persist(self):
        self.plan(); contract=self.h.round('mainline','step'); self.h.builder_stop('done'); self.h.review(Verdict.ADVANCED,'good'); loaded=Humanize(self.root)
        self.assertEqual(loaded.state.phase,Phase.IMPLEMENTATION.value); self.assertNotEqual(loaded.state.builder_session,loaded.state.rounds[0].reviewer_session); self.assertIn('plan_hash',json.loads((self.root/contract).read_text()))
    def test_three_stalls_stop(self):
        self.plan()
        for _ in range(3): self.h.round('mainline','try'); self.h.builder_stop('none'); self.h.review(Verdict.STALLED,'no evidence')
        self.assertTrue(self.h.state.circuit_breaker); self.assertEqual(self.h.state.phase,Phase.STOP.value)
        with self.assertRaises(FlowError): self.h.round('mainline','blocked')
    def test_fifteen_gates(self): self.assertEqual(set(self.h.state.gates),set(GATES))
