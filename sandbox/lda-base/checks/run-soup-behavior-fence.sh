#!/usr/bin/env bash
# Behavior / result-equivalence fence for the soup card: byte-identical
# results through baseline and candidate on the header corpus AND on the
# loopback HTTP roundtrip.
set -euo pipefail
. /opt/lda/harness/checks/soup-workbench.sh
/opt/lda/harness/checks/ensure-pkg-candidate.sh
lda_soup_prepare
corpus=/opt/lda/fixtures/soup/headers-corpus.txt
for iterations in 1 4; do
  base="$(lda_run_with_pkg baseline "$SOUP_FIXDIR/soup-headers" "$corpus" "$iterations")"
  cand="$(lda_run_with_pkg candidate "$SOUP_FIXDIR/soup-headers" "$corpus" "$iterations")"
  test "$base" = "$cand" || { echo "header hash differs at x$iterations" >&2; exit 1; }
  printf 'headers x%s %s\n' "$iterations" "$cand"
done
client=/opt/lda/fixtures/soup/http-client.py
server=/opt/lda/fixtures/soup/http-server.py
python3 "$server" >/opt/lda/soup-port.txt &
server_pid=$!
trap 'kill "$server_pid" 2>/dev/null || true' EXIT
sleep 1
port="$(head -1 /opt/lda/soup-port.txt)"
base="$(lda_run_with_pkg baseline python3 "$client" "http://127.0.0.1:$port" 25)"
cand="$(lda_run_with_pkg candidate python3 "$client" "http://127.0.0.1:$port" 25)"
test "$base" = "$cand" || { echo "http roundtrip digest differs" >&2; exit 1; }
printf 'http %s\n' "$cand"
