import json
import subprocess
import tempfile
import unittest
from pathlib import Path

from lda.benchmarks.portfolio_e2e import config_hash, parse_result, validate_config


class PortfolioHarnessIntegrationTest(unittest.TestCase):
    def test_local_web_and_browser_protocol(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); baseline = root / "baseline"; candidate = root / "candidate"
            baseline.mkdir(); candidate.mkdir()
            page = "<!doctype html><title>LDA</title><div id=x>LDA_E2E_READY</div><script>for(let i=0;i<1000;i++)x.textContent='LDA_E2E_READY '+i</script>"
            (baseline / "index.html").write_text(page, encoding="utf-8")
            (candidate / "index.html").write_text(page, encoding="utf-8")
            # A deterministic browser-protocol fixture for local integration.
            # The E2B template invokes actual Chromium with the same arguments.
            browser = root / "browser-fixture"
            browser.write_text("#!/usr/bin/env python3\nimport sys,urllib.request\nprint(urllib.request.urlopen(sys.argv[-1]).read().decode())\n", encoding="utf-8")
            browser.chmod(0o755)
            raw = {"warmups": 0, "samples": 2,
                   "baseline": {"document_root": str(baseline), "env": {}},
                   "candidate": {"document_root": str(candidate), "env": {}},
                   "workloads": [
                       {"name": "web", "kind": "web_server", "iterations": 1},
                       {"name": "chrome", "kind": "chrome_gui", "iterations": 1}]}
            config = validate_config(raw); config_path = root / "config.json"; output = root / "result.json"
            config_path.write_text(json.dumps(raw), encoding="utf-8")
            script = Path(__file__).parents[2] / "e2b_templates/lda-e2e/run_portfolio_e2e.py"
            run = subprocess.run(["python3", str(script), "--config", str(config_path), "--output", str(output),
                                  "--browser", str(browser)], text=True, capture_output=True, timeout=120)
            self.assertEqual(run.returncode, 0, run.stderr)
            result = parse_result(run.stdout, expected_config_hash=config_hash(config))
            self.assertFalse(result["invalid"], result)
            self.assertEqual(set(result["workloads"]), {"web", "chrome"})
            self.assertTrue(output.is_file())


if __name__ == "__main__": unittest.main()
