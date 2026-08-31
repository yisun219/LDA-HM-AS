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
# One repetition must run for seconds, not tens of milliseconds: at 60
# corpus passes a sample lasted ~65 ms and process start-up plus scheduler
# jitter alone exceeded the 1-2% targets on every window. 2400 passes puts a
# sample in the 2-4 s band where the paired policy resolves 1%.
iterations=$((2400 * mult))

# Warmup (unmeasured).
lda_run_with_pkg "$mode" "$SOUP_FIXDIR/soup-headers" "$corpus" 40 >/dev/null

lda_bench_run micro header-churn "$mode" "$iterations" \
  lda_run_with_pkg "$mode" "$SOUP_FIXDIR/soup-headers" "$corpus" "$iterations"

printf 'soup headers micro mode=%s complete\n' "$mode"
