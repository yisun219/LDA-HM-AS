#!/usr/bin/env bash
# FFI fence for the gtk cards: the consumer binary was compiled ONCE against
# the baseline ABI surface; running it unmodified against the candidate
# library and getting identical styles, colors, and layout results is the
# drop-in proof, for the compiled surface and the gi binding surface alike.
set -euo pipefail
. /opt/lda/harness/checks/gtk-workbench.sh
/opt/lda/harness/checks/ensure-pkg-candidate.sh
lda_gtk_prepare
lda_gtk_attribution candidate
major="$(lda_gtk_major)"
fixroot="${LDA_GTK_FIXDIR:-/opt/lda/fixtures/gtk}"
base="$(lda_run_with_pkg baseline "$GTK_BENCHDIR/gtk-ops" "$major" all 3 "$fixroot")"
cand="$(lda_run_with_pkg candidate "$GTK_BENCHDIR/gtk-ops" "$major" all 3 "$fixroot")"
test "$base" = "$cand" || {
  echo "precompiled gtk consumer outputs differ: $base vs $cand" >&2
  exit 1
}
printf 'precompiled gtk%s consumer hash=%s\n' "$major" "$cand"
