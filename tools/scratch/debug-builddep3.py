#!/usr/bin/env python3
import sys
from pathlib import Path
sys.path.insert(0, "/fact_data/yisun/LDA-HM/src")
from lda_hm.sandbox import E2BSandbox
from lda_hm.cli import _card

card = _card(Path("/fact_data/yisun/LDA-HM/examples/libcairo2-card.json"))
sandbox = E2BSandbox.connect(template=card.baseline.template, timeout=2400)
print("sandbox:", sandbox.sandbox_id, flush=True)
sandbox.bootstrap_assets(Path("/fact_data/yisun/LDA-HM/sandbox/lda-base"))
env = ("env", "LDA_BASELINE_APT_SNAPSHOT=" + card.baseline.apt_snapshot)
script = r"""
set -e
snapshot="$LDA_BASELINE_APT_SNAPSHOT"
apt_root=/opt/lda/apt
mkdir -p "$apt_root/lists/partial" "$apt_root/cache/archives/partial"
printf 'Types: deb deb-src\nURIs: %s\nSuites: resolute\nComponents: main restricted universe multiverse\nSigned-By: /usr/share/keyrings/ubuntu-archive-keyring.gpg\n' "$snapshot" >"$apt_root/snapshot.sources"
OPTS="-o Dir::Etc::sourcelist=$apt_root/snapshot.sources -o Dir::Etc::sourceparts=- -o Dir::State::lists=$apt_root/lists -o Dir::Cache=$apt_root/cache -o APT::Get::List-Cleanup=0 -o Acquire::Check-Valid-Until=false"
apt-get $OPTS update >/dev/null 2>&1 || true
echo "== installed vs snapshot libfreetype6:"
dpkg-query -W libfreetype6 || true
apt-cache $OPTS policy libfreetype6 | head -3
cand=$(apt-cache $OPTS policy libfreetype6 | awk '/Candidate:/{print $2}')
echo "== explicit pinned install libfreetype6=$cand:"
sudo -n apt-get $OPTS install -y --allow-downgrades "libfreetype6=$cand" 2>&1 | tail -2
echo "== fetch cairo source:"
mkdir -p /opt/lda/work && cd /opt/lda/work
apt-get $OPTS source cairo=1.18.4-3 >/dev/null 2>&1
echo "== build-dep simulate:"
if sudo -n apt-get $OPTS build-dep -y -s ./cairo-1.18.4 >/opt/lda/bd.log 2>&1; then
  echo BUILD-DEP-SIM-OK
  grep -cE "^Inst" /opt/lda/bd.log || true
else
  echo BUILD-DEP-SIM-FAIL
  grep -E "conflicting|not going to|Depends" /opt/lda/bd.log | head -8
fi
"""
result = sandbox.run(env + ("bash", "-c", script), timeout_seconds=1500)
print("exit:", result.exit_code)
print(result.stdout[-3000:])
print("--- stderr:", result.stderr[-600:])
sandbox.close()
