#!/usr/bin/env bash
set -euo pipefail
exec bash -lc "${LDA_FFI_FENCE_COMMAND:?LDA_FFI_FENCE_COMMAND is required}"
