#!/usr/bin/env bash
set -e
echo probe-start
. /opt/lda/harness/checks/libpng-common.sh
command -v pngcp || dpkg -L libpng-tools 2>/dev/null | grep bin || true
PNGCP="$(command -v pngcp || true)"
test -n "$PNGCP" || { echo NO-PNGCP; exit 3; }
deck=(/opt/lda/fixtures/libpng/e2e-deck/deck-*.png)
out=/tmp/pngcp-out
mkdir -p "$out"
# Attribution probe
libdir="$(lda_libpng_libdir candidate)"
env LD_LIBRARY_PATH="$libdir" LD_DEBUG=libs "$PNGCP" "${deck[0]}" "$out/probe.png" 2>&1 | grep -F "$libdir/libpng16.so.16" >/dev/null \
  && echo attribution-ok || { echo NO-ATTRIBUTION; exit 4; }
for pair in 1 2 3 4 5 6 7 8 9 10; do
  for mode in baseline candidate; do
    libdir="$(lda_libpng_libdir "$mode")"
    s=$(date +%s%N)
    for f in "${deck[@]}"; do
      env LD_LIBRARY_PATH="$libdir" "$PNGCP" "$f" "$out/$(basename "$f")"
    done
    e=$(date +%s%N)
    echo "PNGCP $mode $(( (e-s)/1000000 ))"
  done
done
# equivalence: identical output bytes across modes for one file
libdir_b="$(lda_libpng_libdir baseline)"; libdir_c="$(lda_libpng_libdir candidate)"
env LD_LIBRARY_PATH="$libdir_b" "$PNGCP" "${deck[0]}" "$out/b.png"
env LD_LIBRARY_PATH="$libdir_c" "$PNGCP" "${deck[0]}" "$out/c.png"
cmp -s "$out/b.png" "$out/c.png" && echo bytes-identical || echo bytes-differ
