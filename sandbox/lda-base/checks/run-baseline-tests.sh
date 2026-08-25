#!/usr/bin/env bash
set -euo pipefail
exec bash -lc "${LDA_BASELINE_TEST_COMMAND:?LDA_BASELINE_TEST_COMMAND is required}"
