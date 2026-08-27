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

# Timed consumer run. All timing happens INSIDE the sandbox so the measured
# interval contains no gateway or transport component. Emits exactly one
# machine-readable line:
#   LDA_BENCH {"layer":...,"input":...,"mode":...,"seconds":...,...}
lda_bench_consumer() {
  local layer="${1:?layer required}"
  local input="${2:?input name required}"
  local mode="${3:?mode required}"
  local fixture="${4:?fixture path required}"
  local iterations="${5:?iteration count required}"
  local consumer="${6:?consumer path required}"
  local load1 steal_before steal_after start_ns end_ns hash seconds
  load1="$(cut -d' ' -f1 /proc/loadavg)"
  steal_before="$(awk '/^cpu /{print $9}' /proc/stat)"
  start_ns="$(date +%s%N)"
  hash="$(lda_run_with_libpng "$mode" "$consumer" "$fixture" "$iterations")"
  end_ns="$(date +%s%N)"
  steal_after="$(awk '/^cpu /{print $9}' /proc/stat)"
  seconds="$(awk -v a="$start_ns" -v b="$end_ns" 'BEGIN{printf "%.6f", (b-a)/1e9}')"
  printf 'LDA_BENCH {"layer":"%s","input":"%s","mode":"%s","seconds":%s,"iterations":%s,"hash":"%s","load1":%s,"steal_ticks":%s}\n' \
    "$layer" "$input" "$mode" "$seconds" "$iterations" "$hash" "$load1" "$((steal_after - steal_before))"
}
