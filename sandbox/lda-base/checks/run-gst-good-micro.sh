#!/usr/bin/env bash
set -euo pipefail
mode="${1:-candidate}"; case "$mode" in baseline|candidate) ;; *) exit 64 ;; esac
. /opt/lda/harness/checks/gst-workbench.sh
if test "$mode" = candidate; then /opt/lda/harness/checks/ensure-pkg-candidate.sh; fi
lda_gst_env "$mode"
lda_gst_attribution "$mode"
mult="${LDA_GST_ITER_MULT:-1}"
vf=$((240 * mult)) ve=$((160 * mult)) au=$((20000 * mult))
lda_gst_video_filters "$mode" 10 >/dev/null
lda_bench_run micro video-filters "$mode" "$vf" lda_gst_video_filters "$mode" "$vf"
lda_bench_run micro video-effects "$mode" "$ve" lda_gst_video_effects "$mode" "$ve"
lda_bench_run micro audio-fx "$mode" "$au" lda_gst_audio_fx "$mode" "$au"
printf 'gst-good micro mode=%s complete\n' "$mode"
