#!/usr/bin/env bash
set -euo pipefail
if test -n "${LDA_BEHAVIOR_FENCE_COMMAND:-}"; then
  exec bash -lc "$LDA_BEHAVIOR_FENCE_COMMAND"
fi
. /opt/lda/harness/checks/libpng-common.sh
consumer=/opt/lda/fixtures/libpng/libpng-consumer
for fixture in /opt/lda/fixtures/libpng/{boundary,small,large,incompressible}.png; do
  baseline="$(lda_run_with_libpng baseline "$consumer" "$fixture" 1)"
  candidate="$(lda_run_with_libpng candidate "$consumer" "$fixture" 1)"
  test "$baseline" = "$candidate"
  printf '%s %s\n' "$(basename "$fixture")" "$candidate"
done
