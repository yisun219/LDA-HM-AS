#!/usr/bin/env bash
# FFI fence for the soup card: consumers compiled/bound once (the dlopen
# header consumer and the python-gi client) run unmodified against the
# candidate library with identical results.
set -euo pipefail
. /opt/lda/harness/checks/soup-workbench.sh
/opt/lda/harness/checks/ensure-pkg-candidate.sh
lda_soup_prepare
corpus=/opt/lda/fixtures/soup/headers-corpus.txt
base="$(lda_run_with_pkg baseline "$SOUP_FIXDIR/soup-headers" "$corpus" 3)"
cand="$(lda_run_with_pkg candidate "$SOUP_FIXDIR/soup-headers" "$corpus" 3)"
test "$base" = "$cand" || { echo "header consumer results differ: $base vs $cand" >&2; exit 1; }
printf 'precompiled soup consumer hash=%s\n' "$cand"
