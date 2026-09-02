#!/usr/bin/env bash
set -euo pipefail
mode="${1:-candidate}"; case "$mode" in baseline|candidate) ;; *) exit 64 ;; esac
. /opt/lda/harness/checks/lo-workbench.sh
lda_lo_env "$mode"
lda_lo_attribution "$mode"
{ lda_lo_convert "$mode" writer; lda_lo_convert "$mode" calc; } | sha256sum | cut -c1-16
