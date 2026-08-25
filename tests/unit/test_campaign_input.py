import hashlib
import tempfile
import unittest
from pathlib import Path

from lda.research.campaign import CANARY, TOP10, prepare


class CampaignInputTest(unittest.TestCase):
    def test_hash_and_top10_are_persisted(self):
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "report.md"
            source.write_text("|1|`libcairo2`|60.20|72|12|12|\n", encoding="utf-8")
            record = prepare(source, tmp)
            self.assertEqual(record.sha256, hashlib.sha256(source.read_bytes()).hexdigest())
            self.assertEqual(record.top10, TOP10)
            self.assertEqual(record.canary, CANARY)
            self.assertTrue((Path(tmp) / record.original_artifact).exists())

