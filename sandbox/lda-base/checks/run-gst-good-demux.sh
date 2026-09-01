#!/usr/bin/env bash
set -euo pipefail
mode="${1:-candidate}"; case "$mode" in baseline|candidate) ;; *) exit 64 ;; esac
. /opt/lda/harness/checks/top10-workbench.sh
lda_top10_prepare; lda_top10_gst_env "$mode"
run() { out="${LDA_REMOTE_TMPDIR:-/scratch/lda-hm}/gst-demux-$mode.raw"; lda_run_with_pkg "$mode" gst-launch-1.0 -q filesrc location="$TOP10_FIXDIR/sample.wav" ! wavparse ! filesink location="$out"; sha256sum "$out" | cut -c1-16; rm -f "$out"; }
run >/dev/null
lda_bench_run micro wav-flac-matroska "$mode" 1 run
