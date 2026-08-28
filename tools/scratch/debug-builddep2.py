#!/usr/bin/env python3
"""Probe: converge installed packages to snapshot versions, then build-dep."""
import sys
from pathlib import Path

sys.path.insert(0, "/fact_data/yisun/LDA-HM/src")
from lda_hm.sandbox import E2BSandbox  # noqa: E402
from lda_hm.cli import _card  # noqa: E402

card = _card(Path("/fact_data/yisun/LDA-HM/examples/libcairo2-card.json"))
sandbox = E2BSandbox.connect(template=card.baseline.template, timeout=3600)
print("sandbox:", sandbox.sandbox_id, flush=True)
sandbox.bootstrap_assets(Path("/fact_data/yisun/LDA-HM/sandbox/lda-base"))

env = ("env", "LDA_BASELINE_APT_SNAPSHOT=" + card.baseline.apt_snapshot)

setup = r"""
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
opts="-o Dir::Etc::sourcelist=$sources -o Dir::Etc::sourceparts=- -o Dir::State::lists=$apt_root/lists -o Dir::Cache=$apt_root/cache -o APT::Get::List-Cleanup=0 -o Acquire::Check-Valid-Until=false"
apt-get $opts update >/dev/null 2>&1 || true
echo "--- policy libfreetype6:"
apt-cache $opts policy libfreetype6 | head -6
echo "--- mismatched installed packages vs snapshot (first 15):"
dpkg-query -W -f='${Package} ${Version}\n' | while read -r pkg ver; do
  cand=$(apt-cache $opts policy "$pkg" 2>/dev/null | awk '/Candidate:/{print $2}')
  if test -n "$cand" && test "$cand" != "(none)" && test "$cand" != "$ver"; then
    echo "$pkg installed=$ver snapshot=$cand"
  fi
done | head -15
echo "--- explicit downgrade probe:"
cand=$(apt-cache $opts policy libfreetype6 | awk '/Candidate:/{print $2}')
sudo apt-get $opts install -y --allow-downgrades "libfreetype6=$cand" 2>&1 | tail -3
echo "--- mkdir work + fetch source:"
mkdir -p /opt/lda/work && cd /opt/lda/work
apt-get $opts source cairo=1.18.4-3 >/dev/null 2>&1 || true
echo "--- build-dep simulate after explicit downgrade:"
sudo apt-get $opts build-dep -y -s ./cairo-1.18.4 2>&1 | tail -3
"""
result = sandbox.run(env + ("bash", "-c", setup), timeout_seconds=1800)
print("exit:", result.exit_code)
print(result.stdout[-4000:])
print("--- stderr:", result.stderr[-1500:])
sandbox.close()
