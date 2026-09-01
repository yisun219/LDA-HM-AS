#!/usr/bin/env bash
set -euo pipefail
. /opt/lda/harness/checks/top10-workbench.sh
lda_top10_prepare
base="$(/opt/lda/harness/checks/run-top10-probe.sh baseline)"
cand="$(/opt/lda/harness/checks/run-top10-probe.sh candidate)"
test -n "$base" && test "$base" = "$cand" || {
  echo "top10 FFI/probe result changed: baseline=$base candidate=$cand" >&2
  exit 1
}
printf 'top10 probe/FFI equivalence hash=%s\n' "$cand"
