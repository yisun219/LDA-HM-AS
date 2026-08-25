import os
import unittest

from lda.e2b.client import E2BClient
from lda.e2b.preflight import Preflight


class RealE2BSmoke(unittest.TestCase):
    @unittest.skipUnless(os.environ.get("E2B_API_KEY"), "requires injected E2B_API_KEY")
    def test_real_preflight(self):
        # This is deliberately opt-in: without the injected key production must fail closed.
        result = Preflight(E2BClient()).run("real-smoke")
        self.assertTrue(result["passed"], result)

