#!/usr/bin/env bash
# Shared helpers for the executable/package top-10 cards.  The selected mode
# is always explicit so a benchmark cannot accidentally execute the host copy.
set -euo pipefail
. /opt/lda/harness/checks/pkg-common.sh

TOP10_FIXDIR=/opt/lda/fixtures/top10

lda_top10_program() {
  local mode="${1:?mode required}" relative="${2:?relative path required}" fallback="${3:?fallback required}"
  local root
  root="$(lda_pkg_root "$mode")"
  if test -x "$root/$relative"; then
    printf '%s\n' "$root/$relative"
  else
    printf '%s\n' "$fallback"
  fi
}

lda_top10_prepare() {
  mkdir -p "$TOP10_FIXDIR" "${LDA_REMOTE_TMPDIR:-/scratch/lda-hm}"
  test -n "${LDA_TOP10_PACKAGE:-}" || {
    echo "LDA_TOP10_PACKAGE is required" >&2
    return 64
  }
}

lda_top10_gst_env() {
  local mode="${1:?mode required}" root scratch
  root="$(lda_pkg_root "$mode")"
  scratch="${LDA_REMOTE_TMPDIR:-/scratch/lda-hm}"
  export GST_PLUGIN_PATH="$root/usr/lib/x86_64-linux-gnu/gstreamer-1.0:/usr/lib/x86_64-linux-gnu/gstreamer-1.0"
  export GST_REGISTRY="$scratch/gst-registry-$mode.bin"
}
