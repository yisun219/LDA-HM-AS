#!/usr/bin/env bash
set -euo pipefail

lda_libpng_root() {
  local mode="${1:?baseline or candidate required}"
  case "$mode" in baseline|candidate) ;; *) return 64 ;; esac
  if test "$mode" = candidate; then
    /opt/lda/harness/checks/ensure-libpng-candidate.sh
  fi
  printf '/opt/lda/%s/root\n' "$mode"
}

lda_libpng_library() {
  local mode="${1:?mode required}"
  cat "/opt/lda/$mode/libpng16.path"
}

lda_libpng_libdir() {
  dirname "$(lda_libpng_library "$1")"
}

lda_run_with_libpng() {
  local mode="${1:?mode required}"
  shift
  local libdir
  libdir="$(lda_libpng_libdir "$mode")"
  env LD_LIBRARY_PATH="$libdir${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}" "$@"
}
