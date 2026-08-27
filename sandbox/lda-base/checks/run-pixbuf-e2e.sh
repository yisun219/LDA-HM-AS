#!/usr/bin/env bash
set -euo pipefail
mode="${1:-candidate}"
case "$mode" in baseline|candidate) ;; *) exit 64 ;; esac
. /opt/lda/harness/checks/libpng-common.sh

# GUI-stack end-to-end workload: the pixbuf-consumer decodes every deck image
# through the real gdk-pixbuf loader pipeline (the code path GTK applications
# use for images), which links the selected libpng. The consumer hashes the
# decoded pixels, so equivalence covers exactly what a GTK application would
# have received. Decode-dominated by construction, so this workload carries a
# nonzero end-to-end speedup requirement.
libdir="$(lda_libpng_libdir "$mode")"
deck=/opt/lda/fixtures/libpng/e2e-deck
consumer=/opt/lda/fixtures/libpng/pixbuf-consumer
# ~15s of measured decode per invocation: long enough that E2B command
# dispatch overhead and scheduler jitter are a rounding error.
passes="${LDA_PIXBUF_PASSES:-40}"
test -x "$consumer" || { echo "pixbuf-consumer is missing" >&2; exit 69; }

deck_files=("$deck"/deck-*.png)
test "${#deck_files[@]}" -ge 8 || { echo "e2e deck missing" >&2; exit 65; }

# Attribution: one probed decode must load the selected library.
probe_log="$(mktemp)"
trap 'rm -f "$probe_log"' EXIT
lda_run_with_libpng "$mode" env LD_DEBUG=libs \
  "$consumer" "${deck_files[0]}" 1 >/dev/null 2>"$probe_log"
grep -F "$libdir/libpng16.so.16" "$probe_log" >/dev/null || {
  echo "pixbuf-consumer did not load $libdir/libpng16.so.16" >&2
  exit 65
}

# Warmup (unmeasured): loader registration, page cache.
lda_run_with_libpng "$mode" "$consumer" "${deck_files[@]:0:4}" 1 >/dev/null

lda_bench_nonce_declare
load1="$(cut -d' ' -f1 /proc/loadavg)"
cpus="$(nproc)"
steal_before="$(awk '/^cpu /{print $9}' /proc/stat)"
start_ns="$(date +%s%N)"
hash="$(lda_run_with_libpng "$mode" "$consumer" "${deck_files[@]}" "$passes" | tail -1)"
end_ns="$(date +%s%N)"
steal_after="$(awk '/^cpu /{print $9}' /proc/stat)"
seconds="$(awk -v a="$start_ns" -v b="$end_ns" 'BEGIN{printf "%.6f", (b-a)/1e9}')"

printf 'LDA_BENCH[%s] {"layer":"end_to_end","input":"pixbuf-decode","mode":"%s","seconds":%s,"iterations":%s,"hash":"%s","load1":%s,"steal_ticks":%s,"cpus":%s}\n' \
  "$_LDA_BENCH_NONCE" "$mode" "$seconds" "$((passes * ${#deck_files[@]}))" "$hash" \
  "$load1" "$((steal_after - steal_before))" "$cpus"

printf 'pixbuf e2e mode=%s passes=%s files=%s complete\n' "$mode" "$passes" "${#deck_files[@]}"
