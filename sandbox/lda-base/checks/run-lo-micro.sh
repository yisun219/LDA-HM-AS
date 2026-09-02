#!/usr/bin/env bash
set -euo pipefail
mode="${1:-candidate}"; case "$mode" in baseline|candidate) ;; *) exit 64 ;; esac
. /opt/lda/harness/checks/lo-workbench.sh
if test "$mode" = candidate; then /opt/lda/harness/checks/ensure-pkg-candidate.sh; fi
lda_lo_env "$mode"
lda_lo_attribution "$mode"
lda_lo_convert "$mode" writer >/dev/null
lda_bench_run micro writer-to-pdf "$mode" 3 lda_lo_convert "$mode" writer
lda_bench_run micro calc-to-pdf "$mode" 3 lda_lo_convert "$mode" calc
printf 'libreoffice micro mode=%s complete\n' "$mode"
