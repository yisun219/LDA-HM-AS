#!/usr/bin/env bash
set -euo pipefail
mode="${1:-candidate}"; case "$mode" in baseline|candidate) ;; *) exit 64 ;; esac
. /opt/lda/harness/checks/top10-workbench.sh
lda_top10_prepare
program="$(lda_top10_program "$mode" usr/lib/libreoffice/program/soffice.bin /usr/lib/libreoffice/program/soffice.bin)"
test -x "$program"
run() { out="${LDA_REMOTE_TMPDIR:-/scratch/lda-hm}/lo-micro-$mode"; rm -rf "$out"; mkdir -p "$out"; lda_run_with_pkg "$mode" "$program" --headless --convert-to pdf --outdir "$out" "$TOP10_FIXDIR/sample.fodt" >/dev/null; sha256sum "$out/sample.pdf" | cut -c1-16; rm -rf "$out"; }
run >/dev/null
lda_bench_run micro fodt-to-pdf "$mode" 1 run
