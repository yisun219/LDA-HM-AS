#!/usr/bin/env bash
set -euo pipefail
base="$(/opt/lda/harness/checks/run-gst-good-probe.sh baseline)"
cand="$(/opt/lda/harness/checks/run-gst-good-probe.sh candidate)"
test -n "$base" && test "$base" = "$cand" || { echo "gst-good probe hash changed: baseline=$base candidate=$cand" >&2; exit 1; }
printf 'gst-good probe/FFI equivalence hash=%s\n' "$cand"
