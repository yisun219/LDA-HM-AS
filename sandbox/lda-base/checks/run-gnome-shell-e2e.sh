#!/usr/bin/env bash
set -euo pipefail
mode="${1:-candidate}"; case "$mode" in baseline|candidate) ;; *) exit 64 ;; esac
. /opt/lda/harness/checks/gnome-shell-workbench.sh
lda_gs_env "$mode"
lda_gs_attribution "$mode"
iters=$((2 * ${LDA_GS_ITER_MULT:-1}))
lda_bench_nonce_declare
lda_gs_iterations "$mode" overview.js "$iters" end_to_end overview-session
printf 'gnome-shell e2e mode=%s complete\n' "$mode"
