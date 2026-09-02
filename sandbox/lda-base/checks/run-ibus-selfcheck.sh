#!/usr/bin/env bash
set -euo pipefail
. /opt/lda/harness/checks/ibus-workbench.sh
for mode in baseline candidate; do
  lda_ibus_env "$mode"; lda_ibus_attribution "$mode"
  a="$(/opt/lda/harness/checks/run-ibus-probe.sh "$mode")"; b="$(/opt/lda/harness/checks/run-ibus-probe.sh "$mode")"
  test "$a" = "$b" || { echo "ibus probe is not deterministic in $mode: $a vs $b" >&2; exit 1; }
done
echo "ibus selfcheck passed"
