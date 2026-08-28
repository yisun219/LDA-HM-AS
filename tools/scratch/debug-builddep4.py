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
apt-get $OPTS update >/dev/null
echo "== madison:"
apt-cache $OPTS madison libfreetype6 | head -2
snapver=$(apt-cache $OPTS madison libfreetype6 | awk '{print $3; exit}')
echo "== explicit downgrade to $snapver:"
sudo -n apt-get $OPTS install -y --allow-downgrades "libfreetype6=$snapver" 2>&1 | tail -3
dpkg-query -W libfreetype6
echo "== mismatch inventory via one madison call:"
dpkg-query -W -f='${Package}\n' | head -400 > /opt/lda/installed.txt
apt-cache $OPTS madison $(cat /opt/lda/installed.txt | tr '\n' ' ') 2>/dev/null | awk '$0 !~ /Sources/ {print $1, $3}' | sort -u -k1,1 > /opt/lda/snapver.txt
dpkg-query -W -f='${Package} ${Version}\n' | sort > /opt/lda/instver.txt
join /opt/lda/instver.txt /opt/lda/snapver.txt | awk '$2 != $3 {print $1, "installed="$2, "snapshot="$3}' | head -20
join /opt/lda/instver.txt /opt/lda/snapver.txt | awk '$2 != $3' | wc -l
echo "== fetch cairo source + build-dep simulate:"
mkdir -p /opt/lda/work && cd /opt/lda/work
apt-get $OPTS source cairo=1.18.4-3 >/dev/null 2>&1
if sudo -n apt-get $OPTS build-dep -y -s ./cairo-1.18.4 >/opt/lda/bd.log 2>&1; then
  echo BUILD-DEP-SIM-OK; grep -cE '^Inst' /opt/lda/bd.log || true
else
  echo BUILD-DEP-SIM-FAIL; grep -E 'conflicting|not going to' /opt/lda/bd.log | head -6
fi
"""
result = sandbox.run(env + ("bash", "-c", script), timeout_seconds=1500)
print("exit:", result.exit_code)
print(result.stdout[-3500:])
print("--- stderr:", result.stderr[-500:])
sandbox.close()
