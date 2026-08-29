#!/usr/bin/env bash
# Known-bad probes for the corrected cairo deck: the owned-code workloads
# must be deterministic and corpus-content-sensitive before any verdict.
set -euo pipefail
. /opt/lda/harness/checks/cairo-workbench.sh

fail() { echo "SELFCHECK FAIL: $*" >&2; exit 1; }
note() { printf 'SELFCHECK %s\n' "$*"; }

lda_cairo_prepare
/opt/lda/harness/checks/run-cairo-selfcheck.sh

export LDA_CAIRO_PATHDIR="${LDA_CAIRO_PATHDIR:-/opt/lda/fixtures/cairo-paths}"
h1="$(lda_run_with_pkg baseline "$CAIRO_FIXDIR/cairo-ops" stroke-dash 2)"
h2="$(lda_run_with_pkg baseline "$CAIRO_FIXDIR/cairo-ops" stroke-dash 2)"
test "$h1" = "$h2" || fail "stroke-dash hash is not deterministic"
variant=/tmp/lda-cairo-owned-selfcheck
rm -rf "$variant"
env LDA_FIXTURE_DIR="$variant" LDA_FIXTURE_SEED=999331 \
  /opt/lda/harness/checks/prepare-cairo-path-fixtures.sh >/dev/null
h3="$(LDA_CAIRO_PATHDIR="$variant" lda_run_with_pkg baseline "$CAIRO_FIXDIR/cairo-ops" stroke-dash 2)"
rm -rf "$variant"
test "$h1" != "$h3" || fail "stroke-dash hash ignores corpus content"
note "owned-code workloads deterministic and corpus-sensitive"
f1="$(lda_run_with_pkg baseline "$CAIRO_FIXDIR/cairo-ops" fill-tess 2)"
f2="$(lda_run_with_pkg baseline "$CAIRO_FIXDIR/cairo-ops" fill-tess 2)"
test "$f1" = "$f2" || fail "fill-tess hash is not deterministic"
note "all owned-deck known-bad probes behaved"
