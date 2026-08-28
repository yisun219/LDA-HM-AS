#!/usr/bin/env python3
import sys
from pathlib import Path
sys.path.insert(0, "/fact_data/yisun/LDA-HM/src")
from lda_hm.sandbox import E2BSandbox
from lda_hm.cli import _card
card = _card(Path("/fact_data/yisun/LDA-HM/examples/libcairo2-card.json"))
sandbox = E2BSandbox.connect(template=card.baseline.template, timeout=900)
sandbox.bootstrap_assets(Path("/fact_data/yisun/LDA-HM/sandbox/lda-base"))
env = ("env", "LDA_BASELINE_APT_SNAPSHOT=" + card.baseline.apt_snapshot)
script = r"""
set -e
apt_root=/opt/lda/apt
mkdir -p "$apt_root/lists/partial" "$apt_root/cache/archives/partial"
printf 'Types: deb deb-src\nURIs: %s\nSuites: resolute\nComponents: main restricted universe multiverse\nSigned-By: /usr/share/keyrings/ubuntu-archive-keyring.gpg\n' "$LDA_BASELINE_APT_SNAPSHOT" >"$apt_root/snapshot.sources"
OPTS="-o Dir::Etc::sourcelist=$apt_root/snapshot.sources -o Dir::Etc::sourceparts=- -o Dir::State::lists=$apt_root/lists -o Dir::Cache=$apt_root/cache -o APT::Get::List-Cleanup=0 -o Acquire::Check-Valid-Until=false"
apt-get $OPTS update >/dev/null
echo "== candidates:"
apt-cache $OPTS madison linux-perf 2>/dev/null | head -2 || true
apt-cache $OPTS madison valgrind 2>/dev/null | head -1 || true
echo "== try install linux-perf:"
if sudo -n apt-get $OPTS install -y linux-perf 2>&1 | tail -1; then
  command -v perf && perf --version || true
  echo "== perf hw:"; timeout 20 perf stat -e cycles,instructions -- sleep 0.05 2>&1 | tail -3 || true
  echo "== perf sw sampling:"; timeout 30 perf record -q --freq 400 -o /tmp/p.data -- sh -c 'x=0; for i in $(seq 300000); do x=$((x+i)); done' 2>&1 | tail -1 || true
  perf report -i /tmp/p.data --stdio --sort dso 2>/dev/null | grep -E "%" | head -4 || true
fi
"""
result = sandbox.run(env + ("bash", "-c", script), timeout_seconds=900)
print("exit:", result.exit_code)
print(result.stdout[-2000:])
print("--- stderr:", result.stderr[-400:])
sandbox.close()
