#!/usr/bin/env bash
set -euo pipefail
mode="${1:-candidate}"; case "$mode" in baseline|candidate) ;; *) exit 64 ;; esac
. /opt/lda/harness/checks/ibus-workbench.sh
lda_ibus_env "$mode"
lda_ibus_attribution "$mode"
{ lda_ibus_registry "$mode" 1; lda_ibus_session "$mode" 300; } | sha256sum | cut -c1-16
