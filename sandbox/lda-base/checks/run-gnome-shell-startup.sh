#!/usr/bin/env bash
set -euo pipefail
mode="${1:-candidate}"; case "$mode" in baseline|candidate) ;; *) exit 64 ;; esac
. /opt/lda/harness/checks/top10-workbench.sh
lda_top10_prepare
program="$(lda_top10_program "$mode" usr/bin/gnome-shell /usr/bin/gnome-shell)"
test -x "$program"
run() { for _ in $(seq 1 40); do lda_run_with_pkg "$mode" "$program" --version 2>&1 || true; done | sha256sum | cut -c1-16; }
run >/dev/null
lda_bench_run micro version-startup "$mode" 40 run
