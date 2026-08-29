#!/usr/bin/env bash
# Micro benchmark for the gtk cards: three gtk workload classes through the
# selected libgtk, each emitted as its own nonce-tagged sample. Iteration
# counts are calibrated per major (gtk3 style resolution costs ~6x gtk4's)
# so every sample lands in the same 2-7s resolution band.
set -euo pipefail
mode="${1:-candidate}"
case "$mode" in baseline|candidate) ;; *) exit 64 ;; esac
. /opt/lda/harness/checks/gtk-workbench.sh
if test "$mode" = candidate; then
  /opt/lda/harness/checks/ensure-pkg-candidate.sh
fi
lda_gtk_prepare
lda_gtk_attribution "$mode"

major="$(lda_gtk_major)"
fixroot="${LDA_GTK_FIXDIR:-/opt/lda/fixtures/gtk}"
mult="${LDA_GTK_ITER_MULT:-1}"
if test "$major" = 4; then
  css_iters=400 style_iters=400 layout_iters=6000
else
  css_iters=300 style_iters=80 layout_iters=6000
fi

# Warmup (unmeasured): faults the library and the display path in.
lda_run_with_pkg "$mode" "$GTK_BENCHDIR/gtk-ops" "$major" all 2 "$fixroot" >/dev/null

lda_bench_run micro css-parse "$mode" $((css_iters * mult)) \
  lda_run_with_pkg "$mode" "$GTK_BENCHDIR/gtk-ops" "$major" css-parse $((css_iters * mult)) "$fixroot"
lda_bench_run micro style-match "$mode" $((style_iters * mult)) \
  lda_run_with_pkg "$mode" "$GTK_BENCHDIR/gtk-ops" "$major" style-match $((style_iters * mult)) "$fixroot"
lda_bench_run micro layout "$mode" $((layout_iters * mult)) \
  lda_run_with_pkg "$mode" "$GTK_BENCHDIR/gtk-ops" "$major" layout $((layout_iters * mult)) "$fixroot"

printf 'gtk%s micro mode=%s complete\n' "$major" "$mode"
