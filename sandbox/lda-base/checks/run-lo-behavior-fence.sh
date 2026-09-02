#!/usr/bin/env bash
set -euo pipefail
for _ in 1 2; do
  base="$(/opt/lda/harness/checks/run-lo-probe.sh baseline)"
  cand="$(/opt/lda/harness/checks/run-lo-probe.sh candidate)"
  test -n "$base" && test "$base" = "$cand" || { echo "libreoffice behavior probe changed: baseline=$base candidate=$cand" >&2; exit 1; }
done
printf 'libreoffice behavior equivalence passed (%s)\n' "$cand"
