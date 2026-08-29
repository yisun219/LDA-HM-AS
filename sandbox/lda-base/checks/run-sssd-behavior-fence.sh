#!/usr/bin/env bash
# Behavior / result-equivalence fence for the sssd card: the whole synthetic
# universe plus the miss namespace must resolve identically through baseline
# and candidate daemons.
set -euo pipefail
. /opt/lda/harness/checks/sssd-workbench.sh
/opt/lda/harness/checks/ensure-pkg-candidate.sh
tool="$(lda_sssd_lookup_tool)"
universe=/tmp/lda-sssd-universe.txt
{ for i in $(seq 0 2999); do echo "lda_u$i"; done
  for i in $(seq 0 199); do echo "lda_missing$i"; done; } >"$universe"

lda_sssd_install_mode baseline
lda_sssd_restart
base="$(python3 "$tool" "$universe" 3200)"
lda_sssd_install_mode candidate
lda_sssd_restart
cand="$(python3 "$tool" "$universe" 3200)"
rm -f "$universe"
test "$base" = "$cand" || { echo "universe resolution differs: $base vs $cand" >&2; exit 1; }
printf 'universe %s\n' "$cand"
