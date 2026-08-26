import json
import tempfile
import unittest
from pathlib import Path

from lda.benchmarks.portfolio_e2e import config_hash, parse_result, validate_config


class PortfolioE2ETest(unittest.TestCase):
    def config(self, root):
        return {"warmups": 1, "samples": 2,
                "baseline": {"document_root": str(root), "env": {}},
                "candidate": {"document_root": str(root), "env": {}},
                "workloads": [
                    {"name": "http", "kind": "web_server", "path": "/index.html", "iterations": 2},
                    {"name": "gui", "kind": "chrome_gui", "path": "/index.html", "iterations": 1}]}

    def test_config_rejects_secret_and_single_kind(self):
        with tempfile.TemporaryDirectory() as tmp:
            raw = self.config(Path(tmp)); raw["candidate"]["env"] = {"API_KEY": "secret"}
            with self.assertRaises(ValueError): validate_config(raw)
            raw = self.config(Path(tmp)); raw["workloads"][1]["kind"] = "web_server"
            with self.assertRaises(ValueError): validate_config(raw)

    def test_parser_recomputes_speedups_from_raw_samples(self):
        with tempfile.TemporaryDirectory() as tmp:
            config = validate_config(self.config(Path(tmp)))
            payload = {"schema": "lda.portfolio-e2e.v1", "config_sha256": config_hash(config),
                       "workloads": {"http": 2.0, "gui": 1.0},
                       "raw_workloads": {
                           "http": {"kind": "web_server", "baseline": [20, 20], "candidate": [10, 10]},
                           "gui": {"kind": "chrome_gui", "baseline": [10, 10], "candidate": [10, 10]}},
                       "geomean_speedup": 2 ** 0.5, "metadata": {"network_scope": "loopback-only"}}
            result = parse_result(json.dumps(payload), expected_config_hash=config_hash(config))
            self.assertFalse(result["invalid"])
            self.assertEqual(result["improved_workloads"], 1)

    def test_parser_fails_closed_on_claimed_reward_mismatch(self):
        payload = {"schema": "lda.portfolio-e2e.v1", "workloads": {"http": 9.0, "gui": 1.0},
                   "raw_workloads": {
                       "http": {"kind": "web_server", "baseline": [20, 20], "candidate": [10, 10]},
                       "gui": {"kind": "chrome_gui", "baseline": [10, 10], "candidate": [10, 10]}},
                   "geomean_speedup": 3.0}
        self.assertTrue(parse_result(json.dumps(payload))["invalid"])

    def test_parser_requires_loopback_network_evidence(self):
        payload = {"schema": "lda.portfolio-e2e.v1", "workloads": {"http": 1.0, "gui": 1.0},
                   "raw_workloads": {
                       "http": {"kind": "web_server", "baseline": [10, 10], "candidate": [10, 10]},
                       "gui": {"kind": "chrome_gui", "baseline": [10, 10], "candidate": [10, 10]}},
                   "geomean_speedup": 1.0, "metadata": {"network_scope": "unrestricted"}}
        result = parse_result(json.dumps(payload))
        self.assertTrue(result["invalid"])
        self.assertEqual(result["reason"], "network_scope_not_verified")


if __name__ == "__main__": unittest.main()
