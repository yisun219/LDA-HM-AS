#!/usr/bin/env bash
set -euo pipefail
. /opt/lda/harness/checks/lo-workbench.sh
# The candidate build at round 0 is the baseline source rebuilt: an A-A pair
# for falsifying the instrument before any patch exists.
/opt/lda/harness/checks/ensure-pkg-candidate.sh
for mode in baseline candidate; do
  lda_lo_env "$mode"; lda_lo_attribution "$mode"
  a="$(/opt/lda/harness/checks/run-lo-probe.sh "$mode")"; b="$(/opt/lda/harness/checks/run-lo-probe.sh "$mode")"
  test -n "$a" && test "$a" = "$b" || { echo "libreoffice probe is not deterministic in $mode: $a vs $b" >&2; exit 1; }
done
echo "libreoffice selfcheck passed"
