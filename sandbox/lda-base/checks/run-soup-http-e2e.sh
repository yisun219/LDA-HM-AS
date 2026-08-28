#!/usr/bin/env bash
# End-to-end benchmark for the soup card: a python3-gi HTTP client (an
# unmodified compiled-binding consumer) against a local loopback server,
# request+response header path through the SELECTED libsoup3.
set -euo pipefail
mode="${1:-candidate}"
case "$mode" in baseline|candidate) ;; *) exit 64 ;; esac
. /opt/lda/harness/checks/soup-workbench.sh
if test "$mode" = candidate; then
  /opt/lda/harness/checks/ensure-pkg-candidate.sh
fi
lda_soup_prepare
lda_soup_attribution "$mode"

client=/opt/lda/fixtures/soup/http-client.py
server=/opt/lda/fixtures/soup/http-server.py
test -s "$client" && test -s "$server" || {
  echo "soup http workbench scripts missing (install-soup-workbench.sh)" >&2
  exit 65
}
python3 "$server" >/opt/lda/fixtures/../soup-port.txt &
server_pid=$!
trap 'kill "$server_pid" 2>/dev/null || true' EXIT
sleep 1
port="$(head -1 /opt/lda/soup-port.txt)"
test -n "$port"

lda_run_with_pkg "$mode" python3 "$client" "http://127.0.0.1:$port" 40 >/dev/null

lda_bench_run end_to_end http-roundtrip "$mode" 400 \
  lda_run_with_pkg "$mode" python3 "$client" "http://127.0.0.1:$port" 400

printf 'soup http e2e mode=%s complete\n' "$mode"
