#!/usr/bin/env bash
# Generic package workbench helpers (multi-arch lib dir selection + the
# nonce-tagged in-sandbox timer shared with the libpng workbench).
set -euo pipefail

lda_pkg_root() {
  local mode="${1:?baseline or candidate required}"
  case "$mode" in baseline|candidate) ;; *) return 64 ;; esac
  printf '/opt/lda/%s/root\n' "$mode"
}

lda_pkg_libdir() {
  local mode="${1:?mode required}"
  printf '%s/usr/lib/x86_64-linux-gnu\n' "$(lda_pkg_root "$mode")"
}

lda_run_with_pkg() {
  local mode="${1:?mode required}"
  shift
  local libdir
  libdir="$(lda_pkg_libdir "$mode")"
  env LD_LIBRARY_PATH="$libdir${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}" "$@"
}

lda_bench_nonce_declare() {
  if test -z "${_LDA_BENCH_NONCE:-}"; then
    _LDA_BENCH_NONCE="$(od -An -N8 -tx8 </dev/urandom | tr -d ' \n')"
    printf 'LDA_BENCH_NONCE %s\n' "$_LDA_BENCH_NONCE"
  fi
}

# lda_bench_run LAYER INPUT MODE ITERATIONS CMD...
# Times one in-sandbox command whose stdout's LAST line is its content hash.
lda_bench_run() {
  local layer="${1:?}" input="${2:?}" mode="${3:?}" iterations="${4:?}"
  shift 4
  local load1 cpus steal_before steal_after start_ns end_ns hash seconds
  lda_bench_nonce_declare
  load1="$(cut -d' ' -f1 /proc/loadavg)"
  cpus="$(nproc)"
  steal_before="$(awk '/^cpu /{print $9}' /proc/stat)"
  start_ns="$(date +%s%N)"
  hash="$("$@" | tail -1)"
  end_ns="$(date +%s%N)"
  steal_after="$(awk '/^cpu /{print $9}' /proc/stat)"
  seconds="$(awk -v a="$start_ns" -v b="$end_ns" 'BEGIN{printf "%.6f", (b-a)/1e9}')"
  printf 'LDA_BENCH[%s] {"layer":"%s","input":"%s","mode":"%s","seconds":%s,"iterations":%s,"hash":"%s","load1":%s,"steal_ticks":%s,"cpus":%s}\n' \
    "$_LDA_BENCH_NONCE" "$layer" "$input" "$mode" "$seconds" "$iterations" "$hash" \
    "$load1" "$((steal_after - steal_before))" "$cpus"
}
