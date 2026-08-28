#!/usr/bin/env bash
# Micro benchmark for the cairo card: four cairo workload classes through the
# selected libcairo2, each emitted as its own nonce-tagged sample.
set -euo pipefail
mode="${1:-candidate}"
case "$mode" in baseline|candidate) ;; *) exit 64 ;; esac
. /opt/lda/harness/checks/cairo-workbench.sh
if test "$mode" = candidate; then
  /opt/lda/harness/checks/ensure-pkg-candidate.sh
fi
lda_cairo_prepare
lda_cairo_attribution "$mode"

fixroot="${LDA_CAIRO_FIXDIR:-/opt/lda/fixtures/libpng}"
pngs=("$fixroot"/boundary.png "$fixroot"/small.png "$fixroot"/large.png "$fixroot"/incompressible.png)
mult="${LDA_CAIRO_ITER_MULT:-1}"

# Warmup (unmeasured).
lda_run_with_pkg "$mode" "$CAIRO_FIXDIR/cairo-ops" all 1 "${pngs[@]}" >/dev/null

lda_bench_run micro png-load "$mode" $((6 * mult)) \
  lda_run_with_pkg "$mode" "$CAIRO_FIXDIR/cairo-ops" png-load $((6 * mult)) "${pngs[@]}"
lda_bench_run micro paint "$mode" $((40 * mult)) \
  lda_run_with_pkg "$mode" "$CAIRO_FIXDIR/cairo-ops" paint $((40 * mult))
lda_bench_run micro mask "$mode" $((30 * mult)) \
  lda_run_with_pkg "$mode" "$CAIRO_FIXDIR/cairo-ops" mask $((30 * mult))
lda_bench_run micro text-path "$mode" $((40 * mult)) \
  lda_run_with_pkg "$mode" "$CAIRO_FIXDIR/cairo-ops" text-path $((40 * mult))

printf 'cairo micro mode=%s complete\n' "$mode"
