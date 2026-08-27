#!/usr/bin/env bash
set -euo pipefail
mode="${1:-candidate}"
case "$mode" in baseline|candidate) ;; *) exit 64 ;; esac
. /opt/lda/harness/checks/libpng-common.sh

# GUI-stack end-to-end workload with verified attribution: the GNOME
# thumbnail pipeline (gdk-pixbuf) decodes every deck image at full size and
# re-encodes a 256px thumbnail, all through the selected libpng. Unlike the
# browser workload this path is decode-dominated, so it is allowed to carry a
# nonzero end-to-end speedup requirement.
command -v gdk-pixbuf-thumbnailer >/dev/null || {
  echo "gdk-pixbuf-thumbnailer is not installed" >&2
  exit 69
}
libdir="$(lda_libpng_libdir "$mode")"
deck=/opt/lda/fixtures/libpng/e2e-deck
consumer=/opt/lda/fixtures/libpng/libpng-consumer
passes="${LDA_PIXBUF_PASSES:-6}"
out="$(mktemp -d)"
trap 'rm -rf "$out"' EXIT

deck_files=("$deck"/deck-*.png)
test "${#deck_files[@]}" -ge 8 || { echo "e2e deck missing" >&2; exit 65; }

# Attribution: one probed run must load the selected library.
lda_run_with_libpng "$mode" env LD_DEBUG=libs \
  gdk-pixbuf-thumbnailer -s 256 "${deck_files[0]}" "$out/probe.png" 2>"$out/probe.log"
grep -F "$libdir/libpng16.so.16" "$out/probe.log" >/dev/null || {
  echo "gdk-pixbuf-thumbnailer did not load $libdir/libpng16.so.16" >&2
  exit 65
}

# Warmup (unmeasured): loader registration, page cache.
for file in "${deck_files[@]:0:4}"; do
  lda_run_with_libpng "$mode" gdk-pixbuf-thumbnailer -s 256 "$file" "$out/warm.png"
done

lda_bench_nonce_declare
load1="$(cut -d' ' -f1 /proc/loadavg)"
cpus="$(nproc)"
steal_before="$(awk '/^cpu /{print $9}' /proc/stat)"
start_ns="$(date +%s%N)"
for pass in $(seq 1 "$passes"); do
  for file in "${deck_files[@]}"; do
    name="$(basename "$file")"
    lda_run_with_libpng "$mode" gdk-pixbuf-thumbnailer -s 256 "$file" "$out/$name"
  done
done
end_ns="$(date +%s%N)"
steal_after="$(awk '/^cpu /{print $9}' /proc/stat)"
seconds="$(awk -v a="$start_ns" -v b="$end_ns" 'BEGIN{printf "%.6f", (b-a)/1e9}')"

# Equivalence: the thumbnails' decoded pixels are hashed through the
# baseline-pinned consumer library, so a candidate whose encoder emits
# different (still valid) bytes passes only if the pixels match.
aggregate=""
for file in "$out"/deck-*.png; do
  digest="$(lda_run_with_libpng baseline "$consumer" "$file" 1)"
  aggregate="$aggregate$digest"
done
hash="$(printf '%s' "$aggregate" | sha256sum | awk '{print $1}')"

printf 'LDA_BENCH[%s] {"layer":"end_to_end","input":"pixbuf-thumbnail","mode":"%s","seconds":%s,"iterations":%s,"hash":"%s","load1":%s,"steal_ticks":%s,"cpus":%s}\n' \
  "$_LDA_BENCH_NONCE" "$mode" "$seconds" "$((passes * ${#deck_files[@]}))" "$hash" \
  "$load1" "$((steal_after - steal_before))" "$cpus"

printf 'pixbuf e2e mode=%s passes=%s files=%s complete\n' "$mode" "$passes" "${#deck_files[@]}"
