#!/usr/bin/env bash
set -euo pipefail
. /opt/lda/harness/checks/gsd-workbench.sh
for mode in baseline candidate; do
  lda_gsd_env "$mode"; lda_gsd_attribution "$mode"
  a="$(/opt/lda/harness/checks/run-gsd-probe.sh "$mode")"; b="$(/opt/lda/harness/checks/run-gsd-probe.sh "$mode")"
  test -n "$a" && test "$a" = "$b" || { echo "gsd probe is not deterministic in $mode: $a vs $b" >&2; exit 1; }
done
echo "gsd selfcheck passed"
