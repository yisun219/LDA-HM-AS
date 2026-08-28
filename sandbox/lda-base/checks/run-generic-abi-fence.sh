#!/usr/bin/env bash
# Generic surgical-replacement ABI fence: every shared library shipped by the
# candidate's runtime debs must be drop-in equal to the baseline's - same
# library set, SONAME, ELF identity, dynamic symbol table, NEEDED set, and
# type-level ABI (abidiff with debug info when the package ships dbgsym).
# Package relationship fields may not change either.
set -euo pipefail
. /opt/lda/harness/checks/libpng-common.sh 2>/dev/null || true

baseline_root=/opt/lda/baseline/root
candidate_root=/opt/lda/candidate/root
test -s /opt/lda/baseline/libraries.list
test -s /opt/lda/candidate/libraries.list

tmp="$(mktemp -d)"
trap 'rm -rf "$tmp"' EXIT

sed "s#^$baseline_root##" /opt/lda/baseline/libraries.list >"$tmp/base.set"
sed "s#^$candidate_root##" /opt/lda/candidate/libraries.list >"$tmp/cand.set"
diff -u "$tmp/base.set" "$tmp/cand.set" || {
  echo "shipped library set changed" >&2
  exit 1
}

failures=0
while IFS= read -r relative; do
  base="$baseline_root$relative"
  cand="$candidate_root$relative"
  for side in base cand; do
    library="${!side}"
    readelf -h "$library" | awk -F: \
      '/Class:|Data:|OS\/ABI:|ABI Version:|Type:|Machine:/ {
         key=$1; sub(/^[[:space:]]+/, "", key)
         value=$2; sub(/^[[:space:]]+/, "", value)
         print key ": " value
       }' >"$tmp/$side.elf"
    readelf -d "$library" | awk '/SONAME|NEEDED/ {print $5}' | LC_ALL=C sort >"$tmp/$side.dyn"
    nm -D --defined-only --format=posix "$library" 2>/dev/null \
      | awk '{print $1, $2}' | LC_ALL=C sort >"$tmp/$side.sym"
  done
  if ! diff -u "$tmp/base.elf" "$tmp/cand.elf" >"$tmp/delta" 2>&1 ||
     ! diff -u "$tmp/base.dyn" "$tmp/cand.dyn" >>"$tmp/delta" 2>&1 ||
     ! diff -u "$tmp/base.sym" "$tmp/cand.sym" >>"$tmp/delta" 2>&1; then
    echo "ABI surface changed for $relative:" >&2
    cat "$tmp/delta" >&2
    failures=$((failures + 1))
    continue
  fi
  if command -v abidiff >/dev/null && test -d "$baseline_root/usr/lib/debug"; then
    set +e
    timeout 600 abidiff \
      --d1 "$baseline_root/usr/lib/debug" --d2 "$candidate_root/usr/lib/debug" \
      "$base" "$cand" >"$tmp/abidiff.out" 2>&1
    abidiff_rc=$?
    set -e
    if test "$abidiff_rc" -eq 124; then
      echo "abidiff exceeded its budget for $relative; ABI equality unproven" >&2
      failures=$((failures + 1))
    elif test "$abidiff_rc" -ne 0; then
      cat "$tmp/abidiff.out" >&2
      echo "abidiff reported ABI differences for $relative" >&2
      failures=$((failures + 1))
    fi
  fi
done <"$tmp/base.set"

paste -d'\n' /opt/lda/baseline/runtime-debs.list /opt/lda/candidate/runtime-debs.list >/dev/null
while IFS= read -r base_deb && IFS= read -r cand_deb <&3; do
  for field in Package Version Architecture Depends Pre-Depends Provides Breaks Conflicts; do
    test "$(dpkg-deb -f "$base_deb" "$field")" = "$(dpkg-deb -f "$cand_deb" "$field")" || {
      echo "package field $field changed for $(dpkg-deb -f "$cand_deb" Package)" >&2
      failures=$((failures + 1))
    }
  done
done </opt/lda/baseline/runtime-debs.list 3</opt/lda/candidate/runtime-debs.list

test "$failures" -eq 0
count="$(wc -l <"$tmp/base.set")"
printf 'generic ABI fence passed over %s libraries\n' "$count"
