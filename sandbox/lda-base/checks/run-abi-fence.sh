#!/usr/bin/env bash
set -euo pipefail
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

# Drop-in means the runtime and packaging dependency surface may not grow: a
# candidate that links one extra shared library or adds a Depends entry is no
# longer installable everywhere the baseline was.
for mode in baseline candidate; do
  library="${!mode}"
  readelf -d "$library" | awk '/NEEDED/ {print $5}' | LC_ALL=C sort >"$tmp/$mode.needed"
done
diff -u "$tmp/baseline.needed" "$tmp/candidate.needed"
baseline_deb="$(cat /opt/lda/baseline/runtime-deb.path)"
candidate_deb="$(cat /opt/lda/candidate/runtime-deb.path)"
for field in Depends Pre-Depends Provides Breaks Conflicts; do
  test "$(dpkg-deb -f "$baseline_deb" "$field")" = \
       "$(dpkg-deb -f "$candidate_deb" "$field")" || {
    echo "candidate package $field changed" >&2
    exit 1
  }
done

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

# Type-level ABI comparison. Symbol-name diffs above cannot see struct layout
# or function-signature changes; abidiff with dbgsym debug info can. Missing
# debug info is a failure ("nobody looked" is not "no difference").
command -v abidiff >/dev/null || { echo "abidiff is not installed" >&2; exit 69; }
test -d "$baseline_root/usr/lib/debug" || { echo "baseline debug info missing" >&2; exit 65; }
test -d "$candidate_root/usr/lib/debug" || { echo "candidate debug info missing" >&2; exit 65; }
set +e
abidiff \
  --d1 "$baseline_root/usr/lib/debug" --d2 "$candidate_root/usr/lib/debug" \
  --headers-dir1 "$baseline_root/usr/include" --headers-dir2 "$candidate_root/usr/include" \
  "$baseline" "$candidate" >"$tmp/abidiff.out" 2>&1
abidiff_rc=$?
set -e
if test "$abidiff_rc" -ne 0; then
  cat "$tmp/abidiff.out" >&2
  echo "abidiff reported ABI differences (exit $abidiff_rc)" >&2
  exit 1
fi

printf '%s\n' "ELF, SONAME, symbol-version, public-header, pkg-config, and abidiff type-level ABI contract passed"
