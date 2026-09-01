#!/usr/bin/env bash
set -euo pipefail
mode="${1:-candidate}"; case "$mode" in baseline|candidate) ;; *) exit 64 ;; esac
. /opt/lda/harness/checks/top10-workbench.sh
lda_top10_prepare; lda_top10_gst_env "$mode"
run() { for _ in $(seq 1 5); do lda_run_with_pkg "$mode" gst-launch-1.0 -q filesrc location="$TOP10_FIXDIR/sample.wav" ! wavparse ! flacenc ! fakesink sync=false >/dev/null; done; sha256sum "$TOP10_FIXDIR/sample.wav" | cut -c1-16; }
run >/dev/null
lda_bench_run end_to_end decode-pipeline "$mode" 5 run
