#!/usr/bin/env bash
# Micro benchmark for the sssd card: the seeded lookup schedule through the
# INSTALLED mode's libnss_sss + sssd_nss + cache pipeline. Mode switching
# (dpkg -i + daemon restart + cache reset + warm) happens outside the timed
# region and costs both modes identically.
set -euo pipefail
mode="${1:-candidate}"
case "$mode" in baseline|candidate) ;; *) exit 64 ;; esac
. /opt/lda/harness/checks/sssd-workbench.sh
if test "$mode" = candidate; then
  /opt/lda/harness/checks/ensure-pkg-candidate.sh
fi
lda_sssd_install_mode "$mode"
lda_sssd_restart
tool="$(lda_sssd_lookup_tool)"
fixdir="${LDA_SSSD_FIXDIR:-$SSSD_FIXDIR_DEFAULT}"
schedule="$fixdir/schedule.txt"
test -s "$schedule" || { echo "lookup schedule missing at $schedule" >&2; exit 66; }
count=$(( ${LDA_SSSD_LOOKUPS:-30000} ))

# Warmup (unmeasured): populate the caches the schedule will hit.
python3 "$tool" "$schedule" 3000 >/dev/null

lda_bench_run micro nss-lookups "$mode" "$count" \
  python3 "$tool" "$schedule" "$count"

printf 'sssd nss micro mode=%s complete\n' "$mode"
