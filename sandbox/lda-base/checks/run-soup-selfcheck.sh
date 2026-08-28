#!/usr/bin/env bash
# Soup-card known-bad probes: this card's own checkers must flag bad samples.
set -euo pipefail
. /opt/lda/harness/checks/soup-workbench.sh
fail() { echo "SELFCHECK FAIL: $*" >&2; exit 1; }
note() { printf 'SELFCHECK %s\n' "$*"; }
lda_soup_prepare
base_lib="$(find /opt/lda/baseline/root -name 'libsoup-3.0.so.0*' -type f | head -1)"
other_lib="$(ldconfig -p | awk '/libz\.so\.1 /{print $NF; exit}')"
test -n "$base_lib" && test -n "$other_lib" || fail "probe libraries unavailable"
if /opt/lda/harness/checks/abi-fence.sh "$base_lib" "$other_lib" >/dev/null 2>&1; then
  fail "abi comparator accepted a wrong pair for the soup card"
fi
note "abi comparator flags a wrong pair"
corpus=/opt/lda/fixtures/soup/headers-corpus.txt
test -s "$corpus" || fail "corpus missing"
h1="$(lda_run_with_pkg baseline "$SOUP_FIXDIR/soup-headers" "$corpus" 2)"
h2="$(lda_run_with_pkg baseline "$SOUP_FIXDIR/soup-headers" "$corpus" 2)"
test "$h1" = "$h2" || fail "soup header hash is not deterministic"
tmp="$(mktemp -d)"
trap 'rm -rf "$tmp"' EXIT
env LDA_FIXTURE_DIR="$tmp" LDA_FIXTURE_SEED=99999 \
  /opt/lda/harness/checks/prepare-soup-fixtures.sh >/dev/null
h3="$(lda_run_with_pkg baseline "$SOUP_FIXDIR/soup-headers" "$tmp/headers-corpus.txt" 2)"
test "$h1" != "$h3" || fail "soup header hash ignores corpus content"
note "soup header hash deterministic and corpus-sensitive"
note "all soup known-bad probes behaved"
