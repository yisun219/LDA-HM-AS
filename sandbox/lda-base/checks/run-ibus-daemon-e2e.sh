#!/usr/bin/env bash
set -euo pipefail
mode="${1:-candidate}"; case "$mode" in baseline|candidate) ;; *) exit 64 ;; esac
. /opt/lda/harness/checks/top10-workbench.sh
lda_top10_prepare
program="$(lda_top10_program "$mode" usr/bin/ibus-daemon /usr/bin/ibus-daemon)"
test -x "$program"
cli="$(lda_top10_program "$mode" usr/bin/ibus /usr/bin/ibus)"
test -x "$cli"
run() { dbus-run-session -- sh -c 'export LD_LIBRARY_PATH="$1${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"; "$2" --daemonize --xim; for i in $(seq 1 8); do "$3" list-engine; done; "$3" exit >/dev/null 2>&1 || true' sh "$(lda_pkg_libdir "$mode")" "$program" "$cli" | sha256sum | cut -c1-16; }
run >/dev/null
lda_bench_run end_to_end daemon-session "$mode" 8 run
