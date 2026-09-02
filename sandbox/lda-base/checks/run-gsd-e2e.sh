#!/usr/bin/env bash
set -euo pipefail
mode="${1:-candidate}"; case "$mode" in baseline|candidate) ;; *) exit 64 ;; esac
. /opt/lda/harness/checks/gsd-workbench.sh
lda_gsd_env "$mode"
lda_gsd_attribution "$mode"
iters=$((15 * ${LDA_GSD_ITER_MULT:-1}))
lda_bench_run end_to_end session-start "$mode" "$iters" lda_gsd_session "$mode" "$iters" parallel
printf 'gsd e2e mode=%s complete\n' "$mode"
