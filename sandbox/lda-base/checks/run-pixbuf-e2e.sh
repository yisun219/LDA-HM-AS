#!/usr/bin/env bash
set -euo pipefail
mode="${1:-candidate}"
case "$mode" in baseline|candidate) ;; *) exit 64 ;; esac
. /opt/lda/harness/checks/libpng-common.sh

# GUI-stack end-to-end workload with verified attribution: gdk-pixbuf (the
# GNOME image loading stack) fully decodes every deck image through its PNG
# loader, which links the selected libpng. gdk-pixbuf-csource emits the
# decoded raw pixels, so the equivalence hash covers exactly what any GTK
# application would have received. Decode-dominated, so this workload is
# allowed to carry a nonzero end-to-end speedup requirement.
command -v gdk-pixbuf-csource >/dev/null || {
  echo "gdk-pixbuf-csource is not installed" >&2
  exit 69
}
libdir="$(lda_libpng_libdir "$mode")"
deck=/opt/lda/fixtures/libpng/e2e-deck
passes="${LDA_PIXBUF_PASSES:-6}"
out="$(mktemp -d)"
trap 'rm -rf "$out"' EXIT

deck_files=("$deck"/deck-*.png)
test "${#deck_files[@]}" -ge 8 || { echo "e2e deck missing" >&2; exit 65; }

# Attribution: one probed decode must load the selected library.
lda_run_with_libpng "$mode" env LD_DEBUG=libs \
  gdk-pixbuf-csource --raw --name=lda_probe "${deck_files[0]}" \
  >"$out/probe.c" 2>"$out/probe.log"
grep -F "$libdir/libpng16.so.16" "$out/probe.log" >/dev/null || {
  echo "gdk-pixbuf did not load $libdir/libpng16.so.16" >&2
  exit 65
}

# Warmup (unmeasured): loader registration, page cache.
for file in "${deck_files[@]:0:4}"; do
  lda_run_with_libpng "$mode" gdk-pixbuf-csource --raw --name=lda_warm "$file" >/dev/null
done

lda_bench_nonce_declare
load1="$(cut -d' ' -f1 /proc/loadavg)"
cpus="$(nproc)"
steal_before="$(awk '/^cpu /{print $9}' /proc/stat)"
start_ns="$(date +%s%N)"
for pass in $(seq 1 "$passes"); do
  index=0
  for file in "${deck_files[@]}"; do
    lda_run_with_libpng "$mode" gdk-pixbuf-csource --raw --name=lda_img \
      "$file" >"$out/decoded-$index.c"
    index=$((index + 1))
  done
done
end_ns="$(date +%s%N)"
steal_after="$(awk '/^cpu /{print $9}' /proc/stat)"
seconds="$(awk -v a="$start_ns" -v b="$end_ns" 'BEGIN{printf "%.6f", (b-a)/1e9}')"

# Equivalence over the decoded pixels themselves (the csource output embeds
# the raw RGBA bytes any GTK consumer would receive).
hash="$(cat "$out"/decoded-*.c | sha256sum | awk '{print $1}')"

printf 'LDA_BENCH[%s] {"layer":"end_to_end","input":"pixbuf-decode","mode":"%s","seconds":%s,"iterations":%s,"hash":"%s","load1":%s,"steal_ticks":%s,"cpus":%s}\n' \
  "$_LDA_BENCH_NONCE" "$mode" "$seconds" "$((passes * ${#deck_files[@]}))" "$hash" \
  "$load1" "$((steal_after - steal_before))" "$cpus"

printf 'pixbuf e2e mode=%s passes=%s files=%s complete\n' "$mode" "$passes" "${#deck_files[@]}"
