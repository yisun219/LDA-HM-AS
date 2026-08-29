#!/usr/bin/env bash
# Behavior / result-equivalence fence for the gtk cards: every workload of the
# precompiled consumer AND the gi-driven churn must produce byte-identical
# results through baseline and candidate libgtk.
set -euo pipefail
. /opt/lda/harness/checks/gtk-workbench.sh
/opt/lda/harness/checks/ensure-pkg-candidate.sh
lda_gtk_prepare
lda_gtk_attribution candidate
major="$(lda_gtk_major)"
fixroot="${LDA_GTK_FIXDIR:-/opt/lda/fixtures/gtk}"
for workload in css-parse style-match layout; do
  base="$(lda_run_with_pkg baseline "$GTK_BENCHDIR/gtk-ops" "$major" "$workload" 3 "$fixroot")"
  cand="$(lda_run_with_pkg candidate "$GTK_BENCHDIR/gtk-ops" "$major" "$workload" 3 "$fixroot")"
  test "$base" = "$cand" || {
    echo "$workload results differ: $base vs $cand" >&2
    exit 1
  }
  printf '%s %s\n' "$workload" "$cand"
done
script=/opt/lda/fixtures/gtk-bench/gi-churn.py
if test -s "$script"; then
  base="$(lda_run_with_pkg baseline python3 "$script" "$major" 3 | tail -1)"
  cand="$(lda_run_with_pkg candidate python3 "$script" "$major" 3 | tail -1)"
  test "$base" = "$cand" || { echo "gi churn results differ" >&2; exit 1; }
  printf 'gi-churn %s\n' "$cand"
fi
