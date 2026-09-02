#!/usr/bin/env bash
set -euo pipefail
mode="${1:-candidate}"; case "$mode" in baseline|candidate) ;; *) exit 64 ;; esac
. /opt/lda/harness/checks/gnome-shell-workbench.sh
lda_gs_env "$mode"
lda_gs_attribution "$mode"
lda_gs_probe_hash "$mode"
