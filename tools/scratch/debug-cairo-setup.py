#!/usr/bin/env python3
"""Debug: reproduce the cairo card setup failure with full output."""
import sys
from pathlib import Path

sys.path.insert(0, "/fact_data/yisun/LDA-HM/src")
from lda_hm.sandbox import E2BSandbox  # noqa: E402
from lda_hm.cli import _card  # noqa: E402


def main() -> int:
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
    # Piecewise replay of prepare-ubuntu-source.sh cairo 1.18.4-3
    steps = [
        ("baseline-verify", env + card.baseline.verification_command()[1:]
         if False else card.baseline.verification_command()),
        ("prepare-bash-x", ("bash", "-x", "/opt/lda/harness/checks/prepare-ubuntu-source.sh", "cairo", "1.18.4-3")),
    ]
    for name, command in steps:
        run_command = command if name == "baseline-verify" else env + tuple(command)
        result = sandbox.run(run_command, timeout_seconds=3600)
        print(f"=== {name}: exit={result.exit_code} ===", flush=True)
        if name != "baseline-verify" or not result.ok:
            print("--- stdout tail ---")
            print(result.stdout[-3000:])
            print("--- stderr tail ---")
            print(result.stderr[-4000:])
        if not result.ok:
            break
    sandbox.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
