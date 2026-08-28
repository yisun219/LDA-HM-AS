#!/usr/bin/env bash
# Micro benchmark for the soup card: the precompiled header-layer consumer
# over the seeded corpus through the SELECTED libsoup3.
#   LDA_SOUP_FIXDIR overrides the corpus root (hidden holdout).
set -euo pipefail
mode="${1:-candidate}"
case "$mode" in baseline|candidate) ;; *) exit 64 ;; esac
. /opt/lda/harness/checks/soup-workbench.sh
if test "$mode" = candidate; then
  /opt/lda/harness/checks/ensure-pkg-candidate.sh
fi
lda_soup_prepare
lda_soup_attribution "$mode"
fixroot="${LDA_SOUP_FIXDIR:-/opt/lda/fixtures/soup}"
corpus="$fixroot/headers-corpus.txt"
test -s "$corpus" || { echo "soup corpus missing at $corpus" >&2; exit 65; }
mult="${LDA_SOUP_ITER_MULT:-1}"

# Warmup (unmeasured).
lda_run_with_pkg "$mode" "$SOUP_FIXDIR/soup-headers" "$corpus" 2 >/dev/null

lda_bench_run micro header-churn "$mode" $((60 * mult)) \
  lda_run_with_pkg "$mode" "$SOUP_FIXDIR/soup-headers" "$corpus" $((60 * mult))

printf 'soup headers micro mode=%s complete\n' "$mode"
