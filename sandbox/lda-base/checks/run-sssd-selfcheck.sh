#!/usr/bin/env bash
# Sssd-card known-bad probes: this card's own checkers must flag bad samples
# before any verdict is trusted.
set -euo pipefail
. /opt/lda/harness/checks/sssd-workbench.sh

fail() { echo "SELFCHECK FAIL: $*" >&2; exit 1; }
note() { printf 'SELFCHECK %s\n' "$*"; }

base_lib="$(find /opt/lda/baseline/root -name 'libnss_sss.so*' -type f | head -1)"
other_lib="$(ldconfig -p | awk '/libz\.so\.1 /{print $NF; exit}')"
test -n "$base_lib" && test -n "$other_lib" || fail "probe libraries unavailable"
if /opt/lda/harness/checks/abi-fence.sh "$base_lib" "$other_lib" >/dev/null 2>&1; then
  fail "abi comparator accepted a wrong pair for the sssd card"
fi
note "abi comparator flags a wrong pair"

lda_sssd_install_mode baseline
lda_sssd_restart
tool="$(lda_sssd_lookup_tool)"
schedule="${LDA_SSSD_FIXDIR:-$SSSD_FIXDIR_DEFAULT}/schedule.txt"
h1="$(python3 "$tool" "$schedule" 5000)"
h2="$(python3 "$tool" "$schedule" 5000)"
test "$h1" = "$h2" || fail "lookup schedule hash is not deterministic"
variant=/tmp/lda-sssd-selfcheck-fixtures
rm -rf "$variant"
env LDA_FIXTURE_DIR="$variant" LDA_FIXTURE_SEED=999331 \
  /opt/lda/harness/checks/prepare-sssd-fixtures.sh >/dev/null
h3="$(python3 "$tool" "$variant/schedule.txt" 5000)"
rm -rf "$variant"
test "$h1" != "$h3" || fail "lookup hash ignores the schedule content"
note "lookup hash deterministic and schedule-sensitive"
note "all sssd known-bad probes behaved"
