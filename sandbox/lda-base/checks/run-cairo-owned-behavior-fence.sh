#!/usr/bin/env bash
# Behavior / result-equivalence fence for the corrected cairo deck: the
# original four workloads AND the three owned-code workloads must render
# byte-identical pixels through baseline and candidate libcairo2.
set -euo pipefail
/opt/lda/harness/checks/run-cairo-behavior-fence.sh
. /opt/lda/harness/checks/cairo-workbench.sh
export LDA_CAIRO_PATHDIR="${LDA_CAIRO_PATHDIR:-/opt/lda/fixtures/cairo-paths}"
for workload in stroke-dash fill-tess text-corpus; do
  base="$(lda_run_with_pkg baseline "$CAIRO_FIXDIR/cairo-ops" "$workload" 2)"
  cand="$(lda_run_with_pkg candidate "$CAIRO_FIXDIR/cairo-ops" "$workload" 2)"
  test "$base" = "$cand" || { echo "$workload pixels differ: $base vs $cand" >&2; exit 1; }
  printf '%s %s\n' "$workload" "$cand"
done
