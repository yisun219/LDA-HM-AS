#!/usr/bin/env bash
set -euo pipefail
. /opt/lda/harness/checks/libpng-common.sh
fixture=/opt/lda/fixtures/libpng/incompressible.png
consumer=/opt/lda/fixtures/libpng/libpng-consumer
baseline="$(lda_run_with_libpng baseline "$consumer" "$fixture" 5)"
candidate="$(lda_run_with_libpng candidate "$consumer" "$fixture" 5)"
test "$baseline" = "$candidate"
printf 'decoded RGBA equivalence hash=%s\n' "$candidate"
