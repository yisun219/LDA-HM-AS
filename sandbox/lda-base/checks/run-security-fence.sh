#!/usr/bin/env bash
set -euo pipefail
exec bash -lc "${LDA_SECURITY_FENCE_COMMAND:?LDA_SECURITY_FENCE_COMMAND is required}"
