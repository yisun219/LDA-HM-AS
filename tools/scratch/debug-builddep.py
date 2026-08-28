#!/usr/bin/env python3
"""Find the apt invocation that satisfies snapshot build-deps in the template."""
import sys
from pathlib import Path

sys.path.insert(0, "/fact_data/yisun/LDA-HM/src")
from lda_hm.sandbox import E2BSandbox  # noqa: E402
from lda_hm.cli import _card  # noqa: E402

card = _card(Path("/fact_data/yisun/LDA-HM/examples/libcairo2-card.json"))
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

# Get the source tree + lists in place (fast path, no build-dep).
setup = """
set -e
snapshot="$LDA_BASELINE_APT_SNAPSHOT"
apt_root=/opt/lda/apt
sources="$apt_root/snapshot.sources"
mkdir -p "$apt_root/lists/partial" "$apt_root/cache/archives/partial"
cat >"$sources" <<EOF
Types: deb deb-src
URIs: $snapshot
Suites: resolute
Components: main restricted universe multiverse
Signed-By: /usr/share/keyrings/ubuntu-archive-keyring.gpg
EOF
apt-get -o Dir::Etc::sourcelist=$sources -o Dir::Etc::sourceparts=- \
  -o Dir::State::lists=$apt_root/lists -o Dir::Cache=$apt_root/cache \
  -o APT::Get::List-Cleanup=0 -o Acquire::Check-Valid-Until=false update 2>&1 | tail -2
mkdir -p /opt/lda/work && cd /opt/lda/work
apt-get -o Dir::Etc::sourcelist=$sources -o Dir::Etc::sourceparts=- \
  -o Dir::State::lists=$apt_root/lists -o Dir::Cache=$apt_root/cache \
  -o APT::Get::List-Cleanup=0 -o Acquire::Check-Valid-Until=false source cairo=1.18.4-3 2>&1 | tail -1
d=$(find . -mindepth 1 -maxdepth 1 -type d | head -1)
echo "source dir: $d"
"""
result = sandbox.run(env + ("bash", "-c", setup), timeout_seconds=1200)
print("setup:", result.exit_code, result.stdout[-500:], result.stderr[-300:], flush=True)

variants = [
    ("allow-downgrades", "build-dep -y --allow-downgrades ./cairo-1.18.4"),
    ("classic-solver", "-o APT::Solver=classic build-dep -y --allow-downgrades ./cairo-1.18.4"),
    ("simulate-plain", "build-dep -y -s ./cairo-1.18.4"),
]
base = (
    "sudo apt-get -o Dir::Etc::sourcelist=/opt/lda/apt/snapshot.sources "
    "-o Dir::Etc::sourceparts=- -o Dir::State::lists=/opt/lda/apt/lists "
    "-o Dir::Cache=/opt/lda/apt/cache -o APT::Get::List-Cleanup=0 "
    "-o Acquire::Check-Valid-Until=false "
)
for name, tail in variants:
    command = base + tail + (" -s" if "simulate" not in name else "")
    result = sandbox.run(("bash", "-c", f"cd /opt/lda/work && {command}"), timeout_seconds=900)
    verdict = "OK" if result.ok else "FAIL"
    print(f"=== {name}: {verdict} (exit={result.exit_code})", flush=True)
    if not result.ok:
        print((result.stderr or result.stdout)[-800:], flush=True)
    else:
        for line in result.stdout.splitlines():
            if "downgraded" in line.lower() or "newly installed" in line.lower():
                print("   ", line.strip())
        break
sandbox.close()
