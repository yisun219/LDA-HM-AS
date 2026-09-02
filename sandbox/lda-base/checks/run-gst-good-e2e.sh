#!/usr/bin/env bash
# Real consumer paths through plugins-good: a WAV -> FLAC-in-Matroska
# transcode (wavparse and audiodynamic are the package's; libFLAC is
# external) and an MJPEG-in-AVI capture-style encode (jpegenc wraps libjpeg;
# avimux is the package's, written to /dev/null since AVI output is timed,
# not hashed).
set -euo pipefail
mode="${1:-candidate}"; case "$mode" in baseline|candidate) ;; *) exit 64 ;; esac
. /opt/lda/harness/checks/gst-workbench.sh
lda_gst_env "$mode"
lda_gst_attribution "$mode"
transcode() {
  {
    lda_run_with_pkg "$mode" gst-launch-1.0 -q filesrc location="$GST_FIXDIR/sample-audio.wav" ! wavparse \
      ! audiodynamic mode=compressor threshold=0.5 ratio=0.4 ! audioconvert ! flacenc ! fdsink fd=1 sync=false
    lda_run_with_pkg "$mode" gst-launch-1.0 -q videotestsrc pattern="$GST_VPATTERN" num-buffers=300 \
      ! "video/x-raw,format=I420,width=$GST_WIDTH,height=$GST_HEIGHT,framerate=30/1" \
      ! jpegenc quality=85 ! avimux ! filesink location=/dev/null sync=false
  } | sha256sum | cut -c1-16
}
transcode >/dev/null
lda_bench_run end_to_end transcode "$mode" 1 transcode
printf 'gst-good e2e mode=%s complete\n' "$mode"
