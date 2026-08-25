#!/usr/bin/env bash
set -euo pipefail
if test -n "${LDA_ABI_FENCE_COMMAND:-}"; then
  exec bash -lc "$LDA_ABI_FENCE_COMMAND"
fi
. /opt/lda/harness/checks/libpng-common.sh
/opt/lda/harness/checks/ensure-libpng-candidate.sh
baseline="$(lda_libpng_library baseline)"
candidate="$(lda_libpng_library candidate)"
baseline_root=/opt/lda/baseline/root
candidate_root=/opt/lda/candidate/root

test "$(readelf -d "$baseline" | awk '/SONAME/ {print $5}')" = \
     "$(readelf -d "$candidate" | awk '/SONAME/ {print $5}')"

tmp="$(mktemp -d)"
trap 'rm -rf "$tmp"' EXIT
for mode in baseline candidate; do
  library="${!mode}"
  readelf -h "$library" | awk -F: \
    '/Class:|Data:|OS\/ABI:|ABI Version:|Type:|Machine:/ {
       key=$1; sub(/^[[:space:]]+/, "", key)
       value=$2; sub(/^[[:space:]]+/, "", value)
       print key ": " value
     }' >"$tmp/$mode.elf"
done
diff -u "$tmp/baseline.elf" "$tmp/candidate.elf"

nm -D --defined-only --format=posix "$baseline" | awk '{print $1, $2}' | LC_ALL=C sort >"$tmp/baseline.symbols"
nm -D --defined-only --format=posix "$candidate" | awk '{print $1, $2}' | LC_ALL=C sort >"$tmp/candidate.symbols"
diff -u "$tmp/baseline.symbols" "$tmp/candidate.symbols"

for mode in baseline candidate; do
  root="${mode}_root"
  root="${!root}"
  (
    cd "$root"
    find usr/include -type f -print0 | LC_ALL=C sort -z | xargs -0 sha256sum
  ) >"$tmp/$mode.headers"
  (
    cd "$root"
    find usr/lib -path '*/pkgconfig/libpng*.pc' -type f -print0 | \
      LC_ALL=C sort -z | xargs -0 sha256sum
  ) >"$tmp/$mode.pkgconfig"
done
sed 's#  usr/#  #g' "$tmp/baseline.headers" >"$tmp/baseline.headers.normalized"
sed 's#  usr/#  #g' "$tmp/candidate.headers" >"$tmp/candidate.headers.normalized"
diff -u "$tmp/baseline.headers.normalized" "$tmp/candidate.headers.normalized"
sed 's#  usr/#  #g' "$tmp/baseline.pkgconfig" >"$tmp/baseline.pkgconfig.normalized"
sed 's#  usr/#  #g' "$tmp/candidate.pkgconfig" >"$tmp/candidate.pkgconfig.normalized"
diff -u "$tmp/baseline.pkgconfig.normalized" "$tmp/candidate.pkgconfig.normalized"

printf '%s\n' "ELF, SONAME, symbol-version, public-header, and pkg-config ABI contract passed"
