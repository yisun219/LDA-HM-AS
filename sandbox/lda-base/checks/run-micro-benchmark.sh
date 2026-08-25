#!/usr/bin/env bash
set -euo pipefail
mode="${1:-candidate}"
if test "$mode" = baseline; then
  exec bash -lc "${LDA_MICRO_BASELINE_COMMAND:?LDA_MICRO_BASELINE_COMMAND is required}"
fi
exec bash -lc "${LDA_MICRO_BENCHMARK_COMMAND:?LDA_MICRO_BENCHMARK_COMMAND is required}"
