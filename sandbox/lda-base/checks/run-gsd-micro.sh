#!/usr/bin/env bash
set -euo pipefail
mode="${1:-candidate}"; case "$mode" in baseline|candidate) ;; *) exit 64 ;; esac
. /opt/lda/harness/checks/gsd-workbench.sh
if test "$mode" = candidate; then /opt/lda/harness/checks/ensure-pkg-candidate.sh; fi
lda_gsd_env "$mode"
lda_gsd_attribution "$mode"
iters=$((15 * ${LDA_GSD_ITER_MULT:-1}))
lda_gsd_session "$mode" 1 serial >/dev/null
lda_bench_run micro plugin-startup "$mode" "$iters" lda_gsd_session "$mode" "$iters" serial
printf 'gsd micro mode=%s complete\n' "$mode"
