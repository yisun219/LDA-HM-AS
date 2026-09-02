#!/usr/bin/env bash
# gstreamer1.0-plugins-good workbench helpers.
#
# The timed pipelines are built from elements the package itself ships
# (videofilter, effectv, audiofx, audiodynamic, level, matroska, avi ...);
# the only external work is the GStreamer core/base scheduling that every
# consumer pays. Each mode (baseline|candidate) sees a private plugin
# directory: the system plugin set with the plugins-good files swapped for
# that mode's build, plus a private registry, so a run can never pick up the
# other mode's plugin by accident and the attribution check can prove which
# file was loaded.
set -euo pipefail
. /opt/lda/harness/checks/pkg-common.sh

GST_FIXDIR="${LDA_GST_FIXDIR:-/opt/lda/fixtures/gst}"
GST_PLUGIN_SUBDIR=usr/lib/x86_64-linux-gnu/gstreamer-1.0

lda_gst_env() {
  local mode="${1:?mode required}" root scratch farm name
  root="$(lda_pkg_root "$mode")"
  scratch="${LDA_REMOTE_TMPDIR:-/scratch/lda-hm}"
  farm="$scratch/gst-plugins-$mode"
  test -d "$root/$GST_PLUGIN_SUBDIR" || {
    echo "no plugins-good build extracted under $root/$GST_PLUGIN_SUBDIR" >&2
    return 66
  }
  rm -rf "$farm"; mkdir -p "$farm"
  for f in /usr/lib/x86_64-linux-gnu/gstreamer-1.0/*.so; do
    name="$(basename "$f")"
    test -e "$root/$GST_PLUGIN_SUBDIR/$name" || ln -s "$f" "$farm/$name"
  done
  for f in "$root/$GST_PLUGIN_SUBDIR"/*.so; do
    ln -s "$f" "$farm/$(basename "$f")"
  done
  export GST_PLUGIN_SYSTEM_PATH_1_0="$farm" GST_PLUGIN_PATH_1_0="" \
    GST_REGISTRY_1_0="$scratch/gst-registry-$mode.bin" GST_REGISTRY_FORK=no \
    GST_DEBUG_NO_COLOR=1 GST_DEBUG=0
  export LDA_GST_ROOT="$root"
  test -s "$GST_FIXDIR/params.env" || {
    echo "gst fixtures missing; run prepare-gst-fixtures.sh first" >&2
    return 66
  }
  # shellcheck disable=SC1090
  . "$GST_FIXDIR/params.env"
}

# Every timed element must come from the mode's own plugins-good build.
lda_gst_attribution() {
  local mode="${1:?mode required}" element file
  for element in videoflip videobalance gamma videomedian videobox videocrop warptv edgetv \
      audiodynamic audiopanorama audioamplify audiokaraoke audioinvert level avimux matroskademux avidemux wavparse jpegenc; do
    file="$(lda_run_with_pkg "$mode" gst-inspect-1.0 "$element" 2>/dev/null \
      | sed -n 's/^ *Filename *//p' | head -1)"
    file="$(readlink -f "$file" 2>/dev/null || printf '%s' "$file")"
    case "$file" in
      "$LDA_GST_ROOT"/*) ;;
      *) echo "element $element resolved to ${file:-nothing}, not under $LDA_GST_ROOT" >&2; return 65 ;;
    esac
  done
}

# gst-launch with stdout reserved for the pipeline's fdsink payload; the
# hash of that payload is the sample's content hash.
lda_gst_hash() {
  local mode="${1:?mode required}"; shift
  lda_run_with_pkg "$mode" gst-launch-1.0 -q "$@" ! fdsink fd=1 sync=false \
    | sha256sum | cut -c1-16
}

lda_gst_video_filters() {
  local mode="$1" frames="$2"
  lda_gst_hash "$mode" videotestsrc pattern="$GST_VPATTERN" num-buffers="$frames" \
    ! "video/x-raw,format=I420,width=$GST_WIDTH,height=$GST_HEIGHT,framerate=30/1" \
    ! videoflip method="$GST_FLIP" ! videobalance saturation=1.3 brightness=0.05 contrast=1.1 \
    ! gamma gamma=1.4 ! videomedian filtersize=5 ! videobox left=-8 top=-8 fill=black \
    ! videocrop left=4 right=4 top=4 bottom=4
}

lda_gst_video_effects() {
  local mode="$1" frames="$2"
  lda_gst_hash "$mode" videotestsrc pattern="$GST_VPATTERN2" num-buffers="$frames" \
    ! "video/x-raw,format=BGRx,width=$GST_WIDTH,height=$GST_HEIGHT,framerate=30/1" \
    ! warptv ! vertigotv ! edgetv ! revtv ! streaktv ! optv
}

lda_gst_audio_fx() {
  local mode="$1" buffers="$2"
  lda_gst_hash "$mode" audiotestsrc wave="$GST_WAVE" freq="$GST_FREQ" num-buffers="$buffers" samplesperbuffer=4096 \
    ! "audio/x-raw,format=S16LE,rate=48000,channels=2,layout=interleaved" \
    ! audiodynamic mode=compressor characteristics=soft-knee threshold=0.4 ratio=0.5 \
    ! audiopanorama panorama=0.35 method=simple ! audioamplify amplification=0.8 clipping-method=wrap-positive \
    ! audiokaraoke level=0.7 mono-level=0.6 ! audioinvert degree=0.25 \
    ! level interval=20000000 ! audiodynamic mode=expander threshold=0.2 ratio=1.6
}

lda_gst_container() {
  # Container round trip (matroska/avi demux of the fixtures, avi and
  # matroska mux to /dev/null). It is part of the equivalence probe, not a
  # timed micro input: at this size the run is process-startup dominated,
  # so it would only dilute the package's share of the timed work. Matroska
  # output carries a random segment UID, so only demuxed payload is hashed.
  local mode="$1" buffers="$2"
  {
    lda_run_with_pkg "$mode" gst-launch-1.0 -q filesrc location="$GST_FIXDIR/sample-audio.mkv" \
      ! matroskademux ! "audio/x-raw" ! fdsink fd=1 sync=false
    lda_run_with_pkg "$mode" gst-launch-1.0 -q filesrc location="$GST_FIXDIR/sample-audio.avi" \
      ! avidemux ! "audio/x-raw" ! fdsink fd=1 sync=false
    lda_run_with_pkg "$mode" gst-launch-1.0 -q audiotestsrc wave="$GST_WAVE" freq="$GST_FREQ" num-buffers="$buffers" samplesperbuffer=512 \
      ! "audio/x-raw,format=S16LE,rate=48000,channels=2" ! avimux ! filesink location=/dev/null sync=false
    lda_run_with_pkg "$mode" gst-launch-1.0 -q audiotestsrc wave="$GST_WAVE" freq="$GST_FREQ" num-buffers="$buffers" samplesperbuffer=512 \
      ! "audio/x-raw,format=S16LE,rate=48000,channels=2" ! matroskamux streamable=true writing-app=lda ! filesink location=/dev/null sync=false
  } | sha256sum | cut -c1-16
}
