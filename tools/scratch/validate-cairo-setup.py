#!/usr/bin/env python3
"""Validate the full cairo card setup + selfchecks in one sandbox."""
import sys, time
from pathlib import Path
sys.path.insert(0, "/fact_data/yisun/LDA-HM/src")
from lda_hm.sandbox import E2BSandbox
from lda_hm.cli import _card

card = _card(Path("/fact_data/yisun/LDA-HM/examples/libcairo2-card.json"))
sandbox = E2BSandbox.connect(template=card.baseline.template, timeout=7200)
print("sandbox:", sandbox.sandbox_id, flush=True)
sandbox.bootstrap_assets(Path("/fact_data/yisun/LDA-HM/sandbox/lda-base"))
env = (
    "env",
    "LDA_BASELINE_MODE=" + card.baseline.mode,
    "LDA_BASELINE_RELEASE=" + card.baseline.release,
    "LDA_BASELINE_CODENAME=" + card.baseline.codename,
    "LDA_BASELINE_APT_SNAPSHOT=" + card.baseline.apt_snapshot,
)
steps = [("setup", env + tuple(c)) for c in card.setup_commands]
steps += [("selfcheck", ("/opt/lda/harness/checks/fence-selfcheck.sh",))]
steps += [("selfcheck", tuple(c)) for c in card.selfcheck_commands]
steps += [("tests-state", ("sh", "-c", "cat /opt/lda/baseline/upstream-tests-state 2>/dev/null; ls /opt/lda/baseline/autopkgtest.summary 2>/dev/null && head -5 /opt/lda/baseline/autopkgtest.summary"))]
for kind, command in steps:
    label = " ".join(command)[-90:]
    started = time.time()
    result = sandbox.run(tuple(command), timeout_seconds=5400)
    status = "OK" if result.ok else f"FAIL exit={result.exit_code}"
    print(f"[{kind}] {status} ({time.time()-started:.0f}s): ...{label}", flush=True)
    if not result.ok:
        print("--- stdout tail ---"); print(result.stdout[-1500:])
        print("--- stderr tail ---"); print(result.stderr[-2500:])
        break
    tail = result.stdout.strip().splitlines()[-1] if result.stdout.strip() else ""
    print("    " + tail[:180], flush=True)
sandbox.close()
