#!/usr/bin/env bash
set -euo pipefail
mode="${1:-candidate}"; case "$mode" in baseline|candidate) ;; *) exit 64 ;; esac
. /opt/lda/harness/checks/top10-workbench.sh
lda_top10_prepare
program="$(lda_top10_program "$mode" usr/bin/ibus-daemon /usr/bin/ibus-daemon)"
test -x "$program"
run() { for _ in $(seq 1 20); do lda_run_with_pkg "$mode" "$program" --version 2>&1; done | sha256sum | cut -c1-16; }
run >/dev/null
lda_bench_run micro engine-list "$mode" 20 run
