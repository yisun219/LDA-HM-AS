#!/usr/bin/env bash
set -euo pipefail
mode="${1:-candidate}"; case "$mode" in baseline|candidate) ;; *) exit 64 ;; esac
. /opt/lda/harness/checks/ibus-workbench.sh
lda_ibus_env "$mode"
lda_ibus_attribution "$mode"
keys=$((12000 * ${LDA_IBUS_ITER_MULT:-1}))
lda_ibus_session "$mode" 200 >/dev/null
lda_bench_run end_to_end key-session "$mode" "$keys" lda_ibus_session "$mode" "$keys"
printf 'ibus e2e mode=%s complete\n' "$mode"
