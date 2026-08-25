#!/usr/bin/env bash
set -euo pipefail
exec bash -lc "${LDA_PACKAGE_LIFECYCLE_COMMAND:?LDA_PACKAGE_LIFECYCLE_COMMAND is required}"
