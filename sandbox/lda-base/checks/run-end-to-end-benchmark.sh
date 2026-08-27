#!/usr/bin/env bash
set -euo pipefail
mode="${1:-candidate}"
case "$mode" in baseline|candidate) ;; *) exit 64 ;; esac
. /opt/lda/harness/checks/libpng-common.sh

libdir="$(lda_libpng_libdir "$mode")"
root=/opt/lda/fixtures/libpng
rounds="${LDA_E2E_ROUNDS:-3}"
port=$((18000 + RANDOM % 20000))

env LD_LIBRARY_PATH="$libdir" LD_DEBUG=libs \
  python3 "$root/png-server.py" "$port" >"/tmp/lda-png-server-$mode.log" 2>&1 &
server_pid=$!
trap 'kill "$server_pid" >/dev/null 2>&1 || true; wait "$server_pid" 2>/dev/null || true' EXIT
for _ in $(seq 1 100); do
  if curl -fsS "http://127.0.0.1:$port/health" >/dev/null; then break; fi
  sleep 0.05
done
curl -fsS "http://127.0.0.1:$port/health" >/dev/null

# Server startup and browser warmup are excluded: browser-render.js performs
# one unmeasured warmup navigation, then times each render inside the sandbox
# and hashes the actual decoded canvas pixels of every image.
load1="$(cut -d' ' -f1 /proc/loadavg)"
cpus="$(nproc)"
steal_before="$(awk '/^cpu /{print $9}' /proc/stat)"
result_json="$(env LD_LIBRARY_PATH="$libdir" NODE_PATH="$(npm root -g)" \
  node "$root/browser-render.js" "http://127.0.0.1:$port/" "$rounds")"
steal_after="$(awk '/^cpu /{print $9}' /proc/stat)"

# Attribution: the timed path must actually have executed the selected
# library. The bundled Chromium statically links its own libpng, so the
# browser side is honest render/network overhead; the candidate library runs
# in the server's PIL encode path (loaded on first image request), and that
# linkage is asserted after the run, not assumed.
grep -F "$libdir/libpng16.so.16" "/tmp/lda-png-server-$mode.log" >/dev/null || {
  echo "png-server did not load $libdir/libpng16.so.16; e2e did not measure the candidate" >&2
  exit 65
}

lda_bench_nonce_declare
python3 - "$mode" "$result_json" "$load1" "$((steal_after - steal_before))" "$cpus" "$_LDA_BENCH_NONCE" <<'PY'
import json
import sys

mode, raw, load1, steal, cpus, nonce = (
    sys.argv[1],
    sys.argv[2],
    float(sys.argv[3]),
    int(sys.argv[4]),
    int(sys.argv[5]),
    sys.argv[6],
)
data = json.loads(raw)
renders = data["renders"]
hashes = data.get("hashes") or []
if not renders:
    raise SystemExit("browser produced no measured renders")
if len(hashes) != len(renders):
    raise SystemExit("browser did not hash every measured render")
if len(set(hashes)) != 1:
    raise SystemExit("rendered pixel hash differs between rounds: " + repr(hashes))
total = sum(float(seconds) for seconds in renders)
for seconds in renders:
    seconds = float(seconds)
    # Machine-wide steal is measured over the whole run; attribute it to each
    # sample proportionally so the per-sample fraction stays meaningful.
    share = int(round(steal * (seconds / total))) if total > 0 else 0
    print(f'LDA_BENCH[{nonce}] ' + json.dumps({
        "layer": "end_to_end",
        "input": "browser-render",
        "mode": mode,
        "seconds": round(seconds, 6),
        "iterations": 1,
        "hash": hashes[0],
        "load1": load1,
        "steal_ticks": share,
        "cpus": cpus,
    }, separators=(",", ":")))
PY

printf 'end-to-end mode=%s rounds=%s complete\n' "$mode" "$rounds"
