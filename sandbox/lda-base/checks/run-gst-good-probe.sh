#!/usr/bin/env bash
# One deterministic pass of every timed element; the FFI/behavior fences
# compare this hash between baseline and candidate.
set -euo pipefail
mode="${1:-candidate}"; case "$mode" in baseline|candidate) ;; *) exit 64 ;; esac
. /opt/lda/harness/checks/gst-workbench.sh
lda_gst_env "$mode"
lda_gst_attribution "$mode"
{ lda_gst_video_filters "$mode" 12; lda_gst_video_effects "$mode" 8; lda_gst_audio_fx "$mode" 600; lda_gst_container "$mode" 600; } | sha256sum | cut -c1-16
