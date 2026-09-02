#!/usr/bin/env bash
set -euo pipefail
for _ in 1 2; do
  base="$(/opt/lda/harness/checks/run-gsd-probe.sh baseline)"
  cand="$(/opt/lda/harness/checks/run-gsd-probe.sh candidate)"
  test -n "$base" && test "$base" = "$cand" || { echo "gsd behavior probe changed: baseline=$base candidate=$cand" >&2; exit 1; }
done
printf 'gsd behavior equivalence passed (%s)\n' "$cand"
