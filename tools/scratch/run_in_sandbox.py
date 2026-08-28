#!/usr/bin/env python3
"""Scratch runner: fresh sandbox + setup + validated patch + a probe script.

Usage: run_in_sandbox.py PROBE_SCRIPT [TIMEOUT_SECONDS]
Never used by the production flow; a debugging convenience only.
"""
import sys
from pathlib import Path

sys.path.insert(0, "/fact_data/yisun/LDA-HM/src")
from lda_hm.sandbox import E2BSandbox  # noqa: E402
from lda_hm.cli import _card  # noqa: E402


def main() -> int:
    probe = Path(sys.argv[1])
    timeout = int(sys.argv[2]) if len(sys.argv) > 2 else 1800
    card = _card(Path("/fact_data/yisun/LDA-HM/examples/libpng-card.json"))
    sandbox = E2BSandbox.connect(template=card.baseline.template, timeout=3600)
    print("sandbox:", sandbox.sandbox_id, flush=True)
    sandbox.bootstrap_assets(Path("/fact_data/yisun/LDA-HM/sandbox/lda-base"))
    env = (
        "env",
        "LDA_BASELINE_MODE=" + card.baseline.mode,
        "LDA_BASELINE_RELEASE=" + card.baseline.release,
        "LDA_BASELINE_CODENAME=" + card.baseline.codename,
        "LDA_BASELINE_APT_SNAPSHOT=" + card.baseline.apt_snapshot,
    )
    for command in card.setup_commands:
        result = sandbox.run(env + tuple(command), timeout_seconds=3600)
        if not result.ok:
            print("SETUP-FAIL", result.stderr[-400:])
            return 1
    result = sandbox.run(
        (
            "sh",
            "-c",
            "cd /opt/lda/work && "
            "git apply /opt/lda/skills/lda-libpng-validated-r0.patch && "
            "git add -A && git commit -qm cand",
        )
    )
    if not result.ok:
        print("PATCH-FAIL", result.stderr[-300:])
        return 1
    result = sandbox.run(
        ("/opt/lda/harness/checks/ensure-libpng-candidate.sh",), timeout_seconds=1800
    )
    print("cand build:", result.ok, flush=True)
    if not result.ok:
        print(result.stderr[-400:])
        return 1
    sandbox.put(probe, "/tmp/probe.sh")
    result = sandbox.run(("bash", "/tmp/probe.sh"), timeout_seconds=timeout)
    print(result.stdout[-6000:], flush=True)
    if not result.ok:
        print("PROBE-ERR:", result.stderr[-800:])
    sandbox.close()
    return 0 if result.ok else 2


if __name__ == "__main__":
    raise SystemExit(main())
