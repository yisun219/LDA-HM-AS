#!/usr/bin/env bash
set -euo pipefail
mode="${1:-candidate}"; case "$mode" in baseline|candidate) ;; *) exit 64 ;; esac
. /opt/lda/harness/checks/gnome-shell-workbench.sh
if test "$mode" = candidate; then /opt/lda/harness/checks/ensure-pkg-candidate.sh; fi
lda_gs_env "$mode"
lda_gs_attribution "$mode"
iters=$((4 * ${LDA_GS_ITER_MULT:-1}))
lda_bench_nonce_declare
lda_gs_iterations "$mode" startup.js "$iters" micro headless-startup
printf 'gnome-shell micro mode=%s complete\n' "$mode"
