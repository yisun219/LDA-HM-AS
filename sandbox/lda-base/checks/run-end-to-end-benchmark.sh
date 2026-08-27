#!/usr/bin/env bash
set -euo pipefail
mode="${1:-candidate}"
if test "$mode" = baseline && test -n "${LDA_END_TO_END_BASELINE_COMMAND:-}"; then
  exec bash -lc "$LDA_END_TO_END_BASELINE_COMMAND"
fi
if test "$mode" = candidate && test -n "${LDA_END_TO_END_BENCHMARK_COMMAND:-}"; then
  exec bash -lc "$LDA_END_TO_END_BENCHMARK_COMMAND"
fi
case "$mode" in baseline|candidate) ;; *) exit 64 ;; esac
. /opt/lda/harness/checks/libpng-common.sh

libdir="$(lda_libpng_libdir "$mode")"
root=/opt/lda/fixtures/libpng
rounds="${LDA_E2E_ROUNDS:-3}"
port=$((18000 + RANDOM % 20000))

env LD_LIBRARY_PATH="$libdir" python3 "$root/png-server.py" "$port" >"/tmp/lda-png-server-$mode.log" 2>&1 &
server_pid=$!
trap 'kill "$server_pid" >/dev/null 2>&1 || true; wait "$server_pid" 2>/dev/null || true' EXIT
for _ in $(seq 1 100); do
  if curl -fsS "http://127.0.0.1:$port/health" >/dev/null; then break; fi
  sleep 0.05
done
curl -fsS "http://127.0.0.1:$port/health" >/dev/null

# Server startup and browser warmup are excluded: browser-render.js performs
# one unmeasured warmup navigation, then times each render inside the sandbox.
load1="$(cut -d' ' -f1 /proc/loadavg)"
steal_before="$(awk '/^cpu /{print $9}' /proc/stat)"
result_json="$(env LD_LIBRARY_PATH="$libdir" NODE_PATH="$(npm root -g)" \
  node "$root/browser-render.js" "http://127.0.0.1:$port/" "$rounds")"
steal_after="$(awk '/^cpu /{print $9}' /proc/stat)"

python3 - "$mode" "$result_json" "$load1" "$((steal_after - steal_before))" <<'PY'
import json
import sys

mode, raw, load1, steal = sys.argv[1], sys.argv[2], float(sys.argv[3]), int(sys.argv[4])
data = json.loads(raw)
renders = data["renders"]
if not renders:
    raise SystemExit("browser produced no measured renders")
for seconds in renders:
    print('LDA_BENCH ' + json.dumps({
        "layer": "end_to_end",
        "input": "browser-render",
        "mode": mode,
        "seconds": round(float(seconds), 6),
        "iterations": 1,
        "hash": str(data.get("images", "")),
        "load1": load1,
        "steal_ticks": steal,
    }, separators=(",", ":")))
PY

printf 'end-to-end mode=%s rounds=%s complete\n' "$mode" "$rounds"
