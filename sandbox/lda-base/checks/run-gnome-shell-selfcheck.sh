#!/usr/bin/env bash
set -euo pipefail
. /opt/lda/harness/checks/gnome-shell-workbench.sh
for mode in baseline candidate; do
  lda_gs_env "$mode"; lda_gs_attribution "$mode"
  a="$(/opt/lda/harness/checks/run-gnome-shell-probe.sh "$mode")"; b="$(/opt/lda/harness/checks/run-gnome-shell-probe.sh "$mode")"
  test -n "$a" && test "$a" = "$b" || { echo "gnome-shell probe is not deterministic in $mode: $a vs $b" >&2; exit 1; }
done
echo "gnome-shell selfcheck passed"
