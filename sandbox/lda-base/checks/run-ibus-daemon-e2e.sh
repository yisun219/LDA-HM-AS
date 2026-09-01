#!/usr/bin/env bash
set -euo pipefail
mode="${1:-candidate}"; case "$mode" in baseline|candidate) ;; *) exit 64 ;; esac
. /opt/lda/harness/checks/top10-workbench.sh
lda_top10_prepare
program="$(lda_top10_program "$mode" usr/bin/ibus-daemon /usr/bin/ibus-daemon)"
test -x "$program"
run() { for _ in $(seq 1 8); do dbus-run-session -- env LD_LIBRARY_PATH="$(lda_pkg_libdir "$mode")${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}" "$program" --version 2>&1 || true; done | sha256sum | cut -c1-16; }
run >/dev/null
lda_bench_run end_to_end daemon-session "$mode" 8 run
