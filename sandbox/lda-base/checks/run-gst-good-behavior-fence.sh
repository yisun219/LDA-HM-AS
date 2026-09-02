#!/usr/bin/env bash
set -euo pipefail
for _ in 1 2 3; do
  base="$(/opt/lda/harness/checks/run-gst-good-probe.sh baseline)"
  cand="$(/opt/lda/harness/checks/run-gst-good-probe.sh candidate)"
  test -n "$base" && test "$base" = "$cand" || { echo "gst-good behavior changed: baseline=$base candidate=$cand" >&2; exit 1; }
done
printf 'gst-good repeated behavior equivalence passed (%s)\n' "$cand"
