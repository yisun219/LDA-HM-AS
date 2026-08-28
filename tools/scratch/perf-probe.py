#!/usr/bin/env python3
import sys
from pathlib import Path
sys.path.insert(0, "/fact_data/yisun/LDA-HM/src")
from lda_hm.sandbox import E2BSandbox
from lda_hm.cli import _card
card = _card(Path("/fact_data/yisun/LDA-HM/examples/libcairo2-card.json"))
sandbox = E2BSandbox.connect(template=card.baseline.template, timeout=900)
print("sandbox:", sandbox.sandbox_id, flush=True)
sandbox.bootstrap_assets(Path("/fact_data/yisun/LDA-HM/sandbox/lda-base"))
env = ("env", "LDA_BASELINE_APT_SNAPSHOT=" + card.baseline.apt_snapshot)
script = r"""
set -e
apt_root=/opt/lda/apt
mkdir -p "$apt_root/lists/partial" "$apt_root/cache/archives/partial"
printf 'Types: deb deb-src\nURIs: %s\nSuites: resolute\nComponents: main restricted universe multiverse\nSigned-By: /usr/share/keyrings/ubuntu-archive-keyring.gpg\n' "$LDA_BASELINE_APT_SNAPSHOT" >"$apt_root/snapshot.sources"
OPTS="-o Dir::Etc::sourcelist=$apt_root/snapshot.sources -o Dir::Etc::sourceparts=- -o Dir::State::lists=$apt_root/lists -o Dir::Cache=$apt_root/cache -o APT::Get::List-Cleanup=0 -o Acquire::Check-Valid-Until=false"
apt-get $OPTS update >/dev/null
echo "== install linux-tools:"
sudo -n apt-get $OPTS install -y linux-tools-common linux-tools-generic 2>&1 | tail -2
echo "== perf locations:"
find /usr/lib/linux-tools* /usr/lib/linux-hwe* -name perf -type f 2>/dev/null
ls /usr/bin/perf 2>/dev/null || echo "no /usr/bin/perf"
perf_binary="$(find /usr/lib -maxdepth 4 -name perf -type f 2>/dev/null | head -1)"
echo "chosen: $perf_binary"
echo "== perf hw:"; timeout 20 "$perf_binary" stat -e cycles,instructions -- sleep 0.05 2>&1 | tail -4 || true
echo "== perf sw:"; timeout 20 "$perf_binary" stat -e task-clock -- sleep 0.05 2>&1 | tail -3 || true
echo "== perf record sw:"; timeout 30 "$perf_binary" record -q --freq 400 -o /tmp/p.data -- sh -c 'for i in $(seq 200000); do :; done' 2>&1 | tail -2 || true
"$perf_binary" report -i /tmp/p.data --stdio --sort dso 2>/dev/null | head -8 || true
"""
result = sandbox.run(env + ("bash", "-c", script), timeout_seconds=900)
print("exit:", result.exit_code)
print(result.stdout[-2500:])
print("--- stderr:", result.stderr[-600:])
sandbox.close()
