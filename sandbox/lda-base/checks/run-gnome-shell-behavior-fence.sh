#!/usr/bin/env bash
set -euo pipefail
for _ in 1 2; do
  base="$(/opt/lda/harness/checks/run-gnome-shell-probe.sh baseline)"
  cand="$(/opt/lda/harness/checks/run-gnome-shell-probe.sh candidate)"
  test -n "$base" && test "$base" = "$cand" || { echo "gnome-shell behavior probe changed: baseline=$base candidate=$cand" >&2; exit 1; }
done
printf 'gnome-shell behavior equivalence passed (%s)\n' "$cand"
