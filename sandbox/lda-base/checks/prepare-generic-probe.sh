#!/usr/bin/env bash
set -euo pipefail

header="${1:?header required}"
body="${2:?loop body required}"
libraries="${3:?link libraries required}"
root=/opt/lda/baseline/root
fixture=/opt/lda/fixtures/generic
mkdir -p "$fixture"
cat >"$fixture/probe.c" <<EOF
#include <$header>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
static volatile uintptr_t sink;
int main(int argc,char **argv) {
  unsigned long loops = argc > 1 ? strtoul(argv[1], 0, 10) : 10000;
  for (unsigned long i=0;i<loops;i++) { $body }
  printf("%lu\\n", (unsigned long)sink);
  return 0;
}
EOF
include_args=()
while IFS= read -r directory; do include_args+=("-I$directory"); done < <(find "$root/usr/include" -type d | sort)
lib_args=()
while IFS= read -r directory; do lib_args+=("-L$directory" "-Wl,-rpath-link,$directory"); done < <(find "$root/usr/lib" -type d | sort)
read -ra requested_libraries <<<"$libraries"
cc -O2 -Werror "${include_args[@]}" "$fixture/probe.c" "${lib_args[@]}" "${requested_libraries[@]}" -o "$fixture/probe"
baseline_libdir="$(dirname "$(head -1 /opt/lda/baseline/libraries.list)")"
LD_LIBRARY_PATH="$baseline_libdir" "$fixture/probe" 10 >"$fixture/baseline-output"
