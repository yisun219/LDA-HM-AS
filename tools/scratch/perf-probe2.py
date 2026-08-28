#!/usr/bin/env python3
import sys
from pathlib import Path
sys.path.insert(0, "/fact_data/yisun/LDA-HM/src")
from lda_hm.sandbox import E2BSandbox
from lda_hm.cli import _card
card = _card(Path("/fact_data/yisun/LDA-HM/examples/libcairo2-card.json"))
sandbox = E2BSandbox.connect(template=card.baseline.template, timeout=600)
script = r"""
dpkg -l 'linux-tools*' 2>/dev/null | tail -4
echo "== files:"
dpkg -L $(dpkg -l 'linux-tools*' 2>/dev/null | awk '/^ii/{print $2}') 2>/dev/null | grep -E 'perf$|bin/' | head -10
echo "== any perf anywhere:"
find / -maxdepth 6 -name perf -type f 2>/dev/null | head -5
"""
result = sandbox.run(("bash", "-c", script), timeout_seconds=300)
print(result.stdout[-1500:])
print("--- stderr:", result.stderr[-300:])
sandbox.close()
