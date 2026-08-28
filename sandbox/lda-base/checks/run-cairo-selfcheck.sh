#!/usr/bin/env bash
# Cairo-card known-bad probes: this card's own checkers must flag bad
# samples before any cairo verdict is trusted.
set -euo pipefail
. /opt/lda/harness/checks/cairo-workbench.sh

fail() { echo "SELFCHECK FAIL: $*" >&2; exit 1; }
note() { printf 'SELFCHECK %s\n' "$*"; }

lda_cairo_prepare

base_lib="$(find /opt/lda/baseline/root -name 'libcairo.so.2*' -type f | head -1)"
other_lib="$(ldconfig -p | awk '/libz\.so\.1 /{print $NF; exit}')"
test -n "$base_lib" && test -n "$other_lib" || fail "probe libraries unavailable"

# The ABI comparator must flag a completely different library.
if /opt/lda/harness/checks/abi-fence.sh "$base_lib" "$other_lib" >/dev/null 2>&1; then
  fail "abi comparator accepted a wrong pair for the cairo card"
fi
note "abi comparator flags a wrong pair"

# The behavior/result-equivalence hash must be deterministic and
# content-sensitive through the precompiled cairo consumer.
fixtures=/opt/lda/fixtures/libpng
h1="$(lda_run_with_pkg baseline "$CAIRO_FIXDIR/cairo-ops" png-load 2 "$fixtures/small.png")"
h2="$(lda_run_with_pkg baseline "$CAIRO_FIXDIR/cairo-ops" png-load 2 "$fixtures/small.png")"
h3="$(lda_run_with_pkg baseline "$CAIRO_FIXDIR/cairo-ops" png-load 2 "$fixtures/large.png")"
test "$h1" = "$h2" || fail "cairo behavior hash is not deterministic"
test "$h1" != "$h3" || fail "cairo behavior hash ignores content"
note "cairo behavior hash deterministic and content-sensitive"

p1="$(lda_run_with_pkg baseline "$CAIRO_FIXDIR/cairo-ops" paint 2)"
p2="$(lda_run_with_pkg baseline "$CAIRO_FIXDIR/cairo-ops" paint 2)"
test "$p1" = "$p2" || fail "cairo paint hash is not deterministic"
note "cairo paint hash deterministic"

note "all cairo known-bad probes behaved"
