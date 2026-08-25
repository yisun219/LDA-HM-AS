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
port=$((18000 + RANDOM % 20000))
env LD_LIBRARY_PATH="$libdir" python3 "$root/png-server.py" "$port" >"/tmp/lda-png-server-$mode.log" 2>&1 &
server_pid=$!
trap 'kill "$server_pid" >/dev/null 2>&1 || true; wait "$server_pid" 2>/dev/null || true' EXIT
for _ in $(seq 1 100); do
  if curl -fsS "http://127.0.0.1:$port/health" >/dev/null; then break; fi
  sleep 0.05
done
curl -fsS "http://127.0.0.1:$port/health" >/dev/null
env LD_LIBRARY_PATH="$libdir" NODE_PATH="$(npm root -g)" \
  node "$root/browser-render.js" "http://127.0.0.1:$port/" | grep -qx 24
printf 'end-to-end mode=%s complete\n' "$mode"
