#!/usr/bin/env bash
set -euo pipefail
mode="${1:-candidate}"; case "$mode" in baseline|candidate) ;; *) exit 64 ;; esac
. /opt/lda/harness/checks/gsd-workbench.sh
lda_gsd_env "$mode"
lda_gsd_attribution "$mode"
{ lda_gsd_session "$mode" 1 serial; lda_gsd_session "$mode" 1 parallel; } | grep '^LDA-GSD' | sha256sum | cut -c1-16
