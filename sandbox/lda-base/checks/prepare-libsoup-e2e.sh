#!/usr/bin/env bash
set -euo pipefail
root=/opt/lda/baseline/root
output=/opt/lda/fixtures/libsoup-e2e
include_args=()
while IFS= read -r directory; do include_args+=("-I$directory"); done < <(find "$root/usr/include" -type d | sort)
lib_args=()
while IFS= read -r directory; do lib_args+=("-L$directory" "-Wl,-rpath-link,$directory"); done < <(find "$root/usr/lib" -type d | sort)
read -ra pkg_args <<<"$(pkg-config --cflags --libs libsoup-3.0)"
cc -O2 -Werror "${include_args[@]}" /opt/lda/fixtures/libsoup-e2e.c "${lib_args[@]}" "${pkg_args[@]}" -o "$output"
baseline_libdir="$(dirname "$(head -1 /opt/lda/baseline/libraries.list)")"
test -x "$output"
LD_LIBRARY_PATH="$baseline_libdir" "$output" 1 http://127.0.0.1:9/ >/dev/null 2>&1 || true
