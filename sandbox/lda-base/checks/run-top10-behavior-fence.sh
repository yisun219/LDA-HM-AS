#!/usr/bin/env bash
set -euo pipefail
. /opt/lda/harness/checks/top10-workbench.sh
lda_top10_prepare
for _ in 1 2 3; do
  base="$(/opt/lda/harness/checks/run-top10-probe.sh baseline)"
  cand="$(/opt/lda/harness/checks/run-top10-probe.sh candidate)"
  test -n "$base" && test "$base" = "$cand" || {
    echo "top10 behavior result changed: baseline=$base candidate=$cand" >&2
    exit 1
  }
done
printf 'top10 repeated behavior equivalence passed (%s)\n' "$cand"
