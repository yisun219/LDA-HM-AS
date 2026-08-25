#!/usr/bin/env bash
set -euo pipefail
exec bash -lc "${LDA_DEPENDENCY_TEST_COMMAND:?LDA_DEPENDENCY_TEST_COMMAND is required}"
