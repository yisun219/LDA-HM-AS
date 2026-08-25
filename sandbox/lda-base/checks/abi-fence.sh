#!/usr/bin/env bash
set -euo pipefail

baseline="${1:?baseline library required}"
candidate="${2:?candidate library required}"
test "$(readelf -d "$baseline" | awk '/SONAME/ {print $5}')" = \
     "$(readelf -d "$candidate" | awk '/SONAME/ {print $5}')"
tmp="$(mktemp -d)"
trap 'rm -rf "$tmp"' EXIT
for library in baseline candidate; do
  path="${!library}"
  readelf -h "$path" | awk -F: \
    '/Class:|Data:|OS\/ABI:|ABI Version:|Type:|Machine:/ {
       key=$1; sub(/^[[:space:]]+/, "", key)
       value=$2; sub(/^[[:space:]]+/, "", value)
       print key ": " value
     }' >"$tmp/$library.elf"
  nm -D --defined-only --format=posix "$path" | awk '{print $1, $2}' | \
    LC_ALL=C sort >"$tmp/$library.symbols"
done
diff -u "$tmp/baseline.elf" "$tmp/candidate.elf"
diff -u "$tmp/baseline.symbols" "$tmp/candidate.symbols"
