#!/usr/bin/env bash
# Micro benchmark for the corrected cairo card: three workloads that live
# entirely inside libcairo2's own rasterization pipeline (stroker, dash
# walker, tessellator, scan converter, toy-text path construction). The
# original png-load/paint/mask deck measured cairo's neighbours (libz,
# pixman); this deck is the package's own code by construction.
set -euo pipefail
mode="${1:-candidate}"
case "$mode" in baseline|candidate) ;; *) exit 64 ;; esac
. /opt/lda/harness/checks/cairo-workbench.sh
if test "$mode" = candidate; then
  /opt/lda/harness/checks/ensure-pkg-candidate.sh
fi
lda_cairo_prepare
lda_cairo_attribution "$mode"

pathdir="${LDA_CAIRO_PATHDIR:-/opt/lda/fixtures/cairo-paths}"
export LDA_CAIRO_PATHDIR="$pathdir"
mult="${LDA_CAIRO_ITER_MULT:-1}"

# Warmup (unmeasured).
lda_run_with_pkg "$mode" "$CAIRO_FIXDIR/cairo-ops" stroke-dash 2 >/dev/null

lda_bench_run micro stroke-dash "$mode" $((80 * mult)) \
  lda_run_with_pkg "$mode" "$CAIRO_FIXDIR/cairo-ops" stroke-dash $((80 * mult))
lda_bench_run micro fill-tess "$mode" $((120 * mult)) \
  lda_run_with_pkg "$mode" "$CAIRO_FIXDIR/cairo-ops" fill-tess $((120 * mult))
lda_bench_run micro text-corpus "$mode" $((60 * mult)) \
  lda_run_with_pkg "$mode" "$CAIRO_FIXDIR/cairo-ops" text-corpus $((60 * mult))

printf 'cairo owned-code micro mode=%s complete\n' "$mode"
