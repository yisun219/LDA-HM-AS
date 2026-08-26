#!/usr/bin/env bash
set -euo pipefail

header="${1:?header required}"
body="${2:?loop body required}"
libraries="${3:?link libraries required}"
modules="${4:-}"
root=/opt/lda/baseline/root
fixture=/opt/lda/fixtures/generic
mkdir -p "$fixture"
cat >"$fixture/probe.c" <<EOF
#include <$header>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
static volatile uintptr_t sink;
int main(int argc,char **argv) {
  unsigned long loops = argc > 1 ? strtoul(argv[1], 0, 10) : 10000;
  const char *distribution = argc > 2 ? argv[2] : "sequential";
  unsigned long input_size = argc > 3 ? strtoul(argv[3], 0, 10) : 64;
  unsigned long seed = argc > 4 ? strtoul(argv[4], 0, 10) : 2604;
  uint64_t state = seed ? seed : 1;
  for (unsigned long iteration=0;iteration<loops;iteration++) {
    unsigned long i = iteration;
    if (strcmp(distribution, "random") == 0) {
      state ^= state << 13; state ^= state >> 7; state ^= state << 17;
      i = (unsigned long)state;
    } else if (strcmp(distribution, "alternating") == 0) {
      i = iteration & 1 ? loops - iteration : iteration;
    }
    $body
  }
  printf("%lu\\n", (unsigned long)sink);
  return 0;
}
EOF
include_args=()
while IFS= read -r directory; do include_args+=("-I$directory"); done < <(find "$root/usr/include" -type d | sort)
lib_args=()
while IFS= read -r directory; do lib_args+=("-L$directory" "-Wl,-rpath-link,$directory"); done < <(find "$root/usr/lib" -type d | sort)
read -ra requested_libraries <<<"$libraries"
pkg_args=()
if test -n "$modules"; then
  IFS=, read -ra requested_modules <<<"$modules"
  read -ra pkg_args <<<"$(pkg-config --cflags --libs "${requested_modules[@]}")"
fi
cc -O2 -Werror "${include_args[@]}" "$fixture/probe.c" "${lib_args[@]}" "${pkg_args[@]}" "${requested_libraries[@]}" -o "$fixture/probe"
baseline_libdir="$(dirname "$(head -1 /opt/lda/baseline/libraries.list)")"
LD_LIBRARY_PATH="$baseline_libdir" "$fixture/probe" 10 >"$fixture/baseline-output"
