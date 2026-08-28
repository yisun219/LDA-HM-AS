#!/usr/bin/env bash
set -e
echo probe-start
. /opt/lda/harness/checks/libpng-common.sh
sudo -n sysctl -q kernel.perf_event_paranoid=-1 2>/dev/null || true
sudo -n sysctl -q kernel.kptr_restrict=0 2>/dev/null || true
PERF="$( { find /usr/lib/linux-tools* /usr/lib/linux-hwe* -maxdepth 3 -name perf -type f 2>/dev/null || true; } | head -1)"
test -n "$PERF" || PERF="$(command -v perf || true)"
echo "perf=$PERF"
test -n "$PERF" || { echo NO-PERF; dpkg -L linux-tools-7.0.0-30 2>/dev/null | head -20; exit 3; }
cd /tmp
for exe in pixbuf-consumer libpng-consumer; do
  for mode in baseline candidate; do
    libdir="$(lda_libpng_libdir "$mode")"
    if test "$exe" = pixbuf-consumer; then
      args="/opt/lda/fixtures/libpng/e2e-deck/deck-00.png"
    else
      args="/opt/lda/fixtures/libpng/large.png"
    fi
    env LD_LIBRARY_PATH="$libdir" "$PERF" record -q -o /tmp/p.data --freq 999 \
      "/opt/lda/fixtures/libpng/$exe" "$args" 60 >/dev/null 2>/tmp/perf.err \
      || { cat /tmp/perf.err; exit 1; }
    echo "=== $exe $mode top symbols ==="
    "$PERF" report -q -i /tmp/p.data --stdio --percent-limit 2 2>/dev/null | head -14
  done
done

echo "===== PNGCP SECTION ====="
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
