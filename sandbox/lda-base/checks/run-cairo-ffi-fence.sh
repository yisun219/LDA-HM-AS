#!/usr/bin/env bash
# FFI fence for the cairo card: the consumer binary was compiled ONCE against
# the baseline ABI surface (dlopen prototypes); running it unmodified against
# the candidate library and getting identical pixels is the drop-in proof.
set -euo pipefail
. /opt/lda/harness/checks/cairo-workbench.sh
/opt/lda/harness/checks/ensure-pkg-candidate.sh
lda_cairo_prepare
lda_cairo_attribution candidate
base="$(lda_run_with_pkg baseline "$CAIRO_FIXDIR/cairo-ops" all 1 /opt/lda/fixtures/libpng/small.png)"
cand="$(lda_run_with_pkg candidate "$CAIRO_FIXDIR/cairo-ops" all 1 /opt/lda/fixtures/libpng/small.png)"
test "$base" = "$cand"
printf 'precompiled cairo consumer hash=%s\n' "$cand"
