#!/usr/bin/env bash
set -euo pipefail
mode="${1:-candidate}"; case "$mode" in baseline|candidate) ;; *) exit 64 ;; esac
. /opt/lda/harness/checks/top10-workbench.sh
lda_top10_prepare
program="$(find "$(lda_pkg_root "$mode")/usr/libexec" -maxdepth 1 -type f -name 'gsd-*' -perm -0100 2>/dev/null | LC_ALL=C sort | head -1)"
test -n "$program" || program="$(find /usr/libexec -maxdepth 1 -type f -name 'gsd-*' -perm -0100 2>/dev/null | LC_ALL=C sort | head -1)"
test -n "$program"
run() { for _ in $(seq 1 8); do dbus-run-session -- env LD_LIBRARY_PATH="$(lda_pkg_libdir "$mode")${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}" timeout 12 "$program" --version 2>&1 || true; done | sha256sum | cut -c1-16; }
run >/dev/null
lda_bench_run end_to_end session-startup "$mode" 8 run
