#!/usr/bin/env bash
set -euo pipefail
for _ in 1 2 3; do
  base="$(/opt/lda/harness/checks/run-ibus-probe.sh baseline)"
  cand="$(/opt/lda/harness/checks/run-ibus-probe.sh candidate)"
  test -n "$base" && test "$base" = "$cand" || { echo "ibus behavior probe changed: baseline=$base candidate=$cand" >&2; exit 1; }
done
printf 'ibus behavior equivalence passed (%s)\n' "$cand"
