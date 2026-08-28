#!/usr/bin/env bash
# Behavior / result-equivalence fence for the cairo card: every cairo-ops
# workload (the precompiled consumer = the FFI surface) must render
# byte-identical pixels through baseline and candidate libcairo2.
set -euo pipefail
. /opt/lda/harness/checks/cairo-workbench.sh
/opt/lda/harness/checks/ensure-pkg-candidate.sh
lda_cairo_prepare
lda_cairo_attribution candidate
pngs=(/opt/lda/fixtures/libpng/{boundary,small,large,incompressible}.png)
for workload in paint mask text-path; do
  base="$(lda_run_with_pkg baseline "$CAIRO_FIXDIR/cairo-ops" "$workload" 2)"
  cand="$(lda_run_with_pkg candidate "$CAIRO_FIXDIR/cairo-ops" "$workload" 2)"
  test "$base" = "$cand" || { echo "$workload pixels differ: $base vs $cand" >&2; exit 1; }
  printf '%s %s\n' "$workload" "$cand"
done
base="$(lda_run_with_pkg baseline "$CAIRO_FIXDIR/cairo-ops" png-load 2 "${pngs[@]}")"
cand="$(lda_run_with_pkg candidate "$CAIRO_FIXDIR/cairo-ops" png-load 2 "${pngs[@]}")"
test "$base" = "$cand" || { echo "png-load pixels differ" >&2; exit 1; }
printf 'png-load %s\n' "$cand"
