#!/usr/bin/env bash
# Gtk-card known-bad probes: this card's own checkers must flag bad samples
# before any gtk verdict is trusted.
set -euo pipefail
. /opt/lda/harness/checks/gtk-workbench.sh

fail() { echo "SELFCHECK FAIL: $*" >&2; exit 1; }
note() { printf 'SELFCHECK %s\n' "$*"; }

lda_gtk_prepare
major="$(lda_gtk_major)"
fixroot="${LDA_GTK_FIXDIR:-/opt/lda/fixtures/gtk}"

soname="$(lda_gtk_soname)"
base_lib="$(find /opt/lda/baseline/root -name "${soname}*" -type f | head -1)"
other_lib="$(ldconfig -p | awk '/libz\.so\.1 /{print $NF; exit}')"
test -n "$base_lib" && test -n "$other_lib" || fail "probe libraries unavailable"

# The ABI comparator must flag a completely different library.
if /opt/lda/harness/checks/abi-fence.sh "$base_lib" "$other_lib" >/dev/null 2>&1; then
  fail "abi comparator accepted a wrong pair for the gtk card"
fi
note "abi comparator flags a wrong pair"

# The behavior hash must be deterministic and fixture-content-sensitive
# through the precompiled gtk consumer.
h1="$(lda_run_with_pkg baseline "$GTK_BENCHDIR/gtk-ops" "$major" all 2 "$fixroot")"
h2="$(lda_run_with_pkg baseline "$GTK_BENCHDIR/gtk-ops" "$major" all 2 "$fixroot")"
test "$h1" = "$h2" || fail "gtk behavior hash is not deterministic"
variant=/tmp/lda-gtk-selfcheck-fixtures
rm -rf "$variant"
env LDA_FIXTURE_DIR="$variant" LDA_FIXTURE_SEED=999331 \
  /opt/lda/harness/checks/prepare-gtk-fixtures.sh >/dev/null
h3="$(lda_run_with_pkg baseline "$GTK_BENCHDIR/gtk-ops" "$major" all 2 "$variant")"
rm -rf "$variant"
test "$h1" != "$h3" || fail "gtk behavior hash ignores fixture content"
note "gtk behavior hash deterministic and fixture-sensitive"

note "all gtk known-bad probes behaved"
