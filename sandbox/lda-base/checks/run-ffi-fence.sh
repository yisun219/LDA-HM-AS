#!/usr/bin/env bash
set -euo pipefail
. /opt/lda/harness/checks/libpng-common.sh
fixture=/opt/lda/fixtures/libpng/small.png
consumer=/opt/lda/fixtures/libpng/libpng-consumer
baseline="$(lda_run_with_libpng baseline "$consumer" "$fixture" 3)"
candidate="$(lda_run_with_libpng candidate "$consumer" "$fixture" 3)"
test "$baseline" = "$candidate"
printf 'precompiled C FFI consumer hash=%s\n' "$candidate"
