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

# Anti-forgery nonce. Candidate library code runs inside the measured
# consumer process and could print fake sample lines to stdout; genuine
# samples are tagged with a nonce generated in THIS shell, which the consumer
# process cannot see (it is never exported). The declaration line is printed
# before any consumer output can appear, and the host parser honors only the
# first declaration.
lda_bench_nonce_declare() {
  # Prints the declaration straight to the script's stdout (never inside a
  # command substitution) and remembers the nonce for later sample lines.
  if test -z "${_LDA_BENCH_NONCE:-}"; then
    _LDA_BENCH_NONCE="$(od -An -N8 -tx8 </dev/urandom | tr -d ' \n')"
    printf 'LDA_BENCH_NONCE %s\n' "$_LDA_BENCH_NONCE"
  fi
}

# Timed consumer run. All timing happens INSIDE the sandbox so the measured
# interval contains no gateway or transport component. Emits exactly one
# machine-readable line:
#   LDA_BENCH[<nonce>] {"layer":...,"input":...,"mode":...,"seconds":...,...}
lda_bench_consumer() {
  local layer="${1:?layer required}"
  local input="${2:?input name required}"
  local mode="${3:?mode required}"
  local fixture="${4:?fixture path required}"
  local iterations="${5:?iteration count required}"
  local consumer="${6:?consumer path required}"
  local load1 cpus steal_before steal_after start_ns end_ns hash seconds
  lda_bench_nonce_declare
  load1="$(cut -d' ' -f1 /proc/loadavg)"
  cpus="$(nproc)"
  steal_before="$(awk '/^cpu /{print $9}' /proc/stat)"
  start_ns="$(date +%s%N)"
  hash="$(lda_run_with_libpng "$mode" "$consumer" "$fixture" "$iterations" | tail -1)"
  end_ns="$(date +%s%N)"
  steal_after="$(awk '/^cpu /{print $9}' /proc/stat)"
  seconds="$(awk -v a="$start_ns" -v b="$end_ns" 'BEGIN{printf "%.6f", (b-a)/1e9}')"
  printf 'LDA_BENCH[%s] {"layer":"%s","input":"%s","mode":"%s","seconds":%s,"iterations":%s,"hash":"%s","load1":%s,"steal_ticks":%s,"cpus":%s}\n' \
    "$_LDA_BENCH_NONCE" "$layer" "$input" "$mode" "$seconds" "$iterations" "$hash" "$load1" "$((steal_after - steal_before))" "$cpus"
}
