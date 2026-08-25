#!/usr/bin/env bash
set -euo pipefail
runtime_packages="${1:?runtime packages required}"
/opt/lda/harness/checks/build-generic-package.sh candidate "$runtime_packages"
candidate_libdir="$(dirname "$(head -1 /opt/lda/candidate/libraries.list)")"
baseline_libdir="$(dirname "$(head -1 /opt/lda/baseline/libraries.list)")"
fixture=/opt/lda/fixtures/generic/probe
test "$(LD_LIBRARY_PATH="$baseline_libdir" "$fixture" 100)" = "$(LD_LIBRARY_PATH="$candidate_libdir" "$fixture" 100)"
