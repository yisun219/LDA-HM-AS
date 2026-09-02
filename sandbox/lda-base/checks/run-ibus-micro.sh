#!/usr/bin/env bash
set -euo pipefail
mode="${1:-candidate}"; case "$mode" in baseline|candidate) ;; *) exit 64 ;; esac
. /opt/lda/harness/checks/ibus-workbench.sh
if test "$mode" = candidate; then /opt/lda/harness/checks/ensure-pkg-candidate.sh; fi
lda_ibus_env "$mode"
lda_ibus_attribution "$mode"
mult="${LDA_IBUS_ITER_MULT:-1}"
rounds=$((6 * mult))
lda_ibus_registry "$mode" 1 >/dev/null
lda_bench_run micro registry "$mode" "$rounds" lda_ibus_registry "$mode" "$rounds"
printf 'ibus micro mode=%s complete\n' "$mode"
