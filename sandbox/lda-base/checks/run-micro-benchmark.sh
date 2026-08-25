#!/usr/bin/env bash
set -euo pipefail
mode="${1:-candidate}"
if test "$mode" = baseline && test -n "${LDA_MICRO_BASELINE_COMMAND:-}"; then
  exec bash -lc "$LDA_MICRO_BASELINE_COMMAND"
fi
if test "$mode" = candidate && test -n "${LDA_MICRO_BENCHMARK_COMMAND:-}"; then
  exec bash -lc "$LDA_MICRO_BENCHMARK_COMMAND"
fi
case "$mode" in baseline|candidate) ;; *) exit 64 ;; esac
. /opt/lda/harness/checks/libpng-common.sh
consumer=/opt/lda/fixtures/libpng/libpng-consumer
root=/opt/lda/fixtures/libpng
lda_run_with_libpng "$mode" "$consumer" "$root/boundary.png" 12000 >/dev/null
lda_run_with_libpng "$mode" "$consumer" "$root/small.png" 1200 >/dev/null
lda_run_with_libpng "$mode" "$consumer" "$root/large.png" 12 >/dev/null
lda_run_with_libpng "$mode" "$consumer" "$root/incompressible.png" 36 >/dev/null
printf 'micro mode=%s complete\n' "$mode"
