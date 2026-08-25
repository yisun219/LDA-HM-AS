#!/usr/bin/env bash
set -euo pipefail
check="${1:?check required}"
baseline_root=/opt/lda/baseline/root
candidate_root=/opt/lda/candidate/root
tmp="$(mktemp -d)"
trap 'rm -rf "$tmp"' EXIT
mapfile -t baseline_libraries </opt/lda/baseline/libraries.list
mapfile -t candidate_libraries </opt/lda/candidate/libraries.list
test "${#baseline_libraries[@]}" = "${#candidate_libraries[@]}"

normalize_library() { basename "$1" | sed -E 's/\.so\..*/.so/'; }
pair_for() {
  local baseline="$1" key candidate
  key="$(normalize_library "$baseline")"
  for candidate in "${candidate_libraries[@]}"; do
    test "$(normalize_library "$candidate")" = "$key" && { printf '%s\n' "$candidate"; return; }
  done
  return 1
}

case "$check" in
  soname|exported-symbols|symbol-versions|abidiff|abi-compliance)
    for baseline in "${baseline_libraries[@]}"; do
      candidate="$(pair_for "$baseline")"
      case "$check" in
        soname) test "$(readelf -d "$baseline" | awk '/SONAME/{print $5}')" = "$(readelf -d "$candidate" | awk '/SONAME/{print $5}')" ;;
        exported-symbols)
          nm -D --defined-only --format=posix "$baseline" | awk '{print $1,$2}' | sort >"$tmp/a"
          nm -D --defined-only --format=posix "$candidate" | awk '{print $1,$2}' | sort >"$tmp/b"
          diff -u "$tmp/a" "$tmp/b" ;;
        symbol-versions)
          readelf --version-info "$baseline" | sed 's/0x[0-9a-fA-F]\+/ADDR/g' >"$tmp/a"
          readelf --version-info "$candidate" | sed 's/0x[0-9a-fA-F]\+/ADDR/g' >"$tmp/b"
          diff -u "$tmp/a" "$tmp/b" ;;
        abidiff) abidiff --no-added-syms "$baseline" "$candidate" ;;
        abi-compliance)
          abi-dumper "$baseline" -o "$tmp/a.dump" -lver baseline
          abi-dumper "$candidate" -o "$tmp/b.dump" -lver candidate
          abi-compliance-checker -l "$(normalize_library "$baseline")" -old "$tmp/a.dump" -new "$tmp/b.dump" ;;
      esac
    done
    ;;
  header-compile)
    test -n "${LDA_PUBLIC_HEADER:-}"
    printf '#include <%s>\nint main(void){return 0;}\n' "$LDA_PUBLIC_HEADER" >"$tmp/test.c"
    includes=(); while IFS= read -r directory; do includes+=("-I$directory"); done < <(find "$candidate_root/usr/include" -type d | sort)
    cc -Werror "${includes[@]}" "$tmp/test.c" -c -o "$tmp/test.o"
    ;;
  struct-layout)
    test -n "${LDA_LAYOUT_BODY:-}"
    printf '#include <%s>\n#include <stdio.h>\nint main(void){%s}\n' "$LDA_PUBLIC_HEADER" "$LDA_LAYOUT_BODY" >"$tmp/layout.c"
    for mode in baseline candidate; do
      root="/opt/lda/$mode/root"; includes=(); while IFS= read -r directory; do includes+=("-I$directory"); done < <(find "$root/usr/include" -type d | sort)
      cc "${includes[@]}" "$tmp/layout.c" -o "$tmp/$mode"
    done
    test "$("$tmp/baseline")" = "$("$tmp/candidate")"
    ;;
  calling-convention)
    for mode in baseline candidate; do readelf -h "$(head -1 /opt/lda/$mode/libraries.list)" | awk -F: '/Class:|Data:|Machine:/{print $1,$2}' >"$tmp/$mode"; done
    diff -u "$tmp/baseline" "$tmp/candidate"
    ;;
  pkg-config|cmake-config|install-paths)
    case "$check" in
      pkg-config) pattern='*/pkgconfig/*.pc' ;;
      cmake-config) pattern='*/cmake/*' ;;
      install-paths) pattern='*' ;;
    esac
    for mode in baseline candidate; do
      root="/opt/lda/$mode/root"
      find "$root" -path "$pattern" \( -type f -o -type l \) | sed "s#$root##" | sort >"$tmp/$mode"
    done
    diff -u "$tmp/baseline" "$tmp/candidate"
    ;;
  precompiled-binary)
    baseline_libdir="$(dirname "$(head -1 /opt/lda/baseline/libraries.list)")"
    candidate_libdir="$(dirname "$(head -1 /opt/lda/candidate/libraries.list)")"
    test "$(LD_LIBRARY_PATH="$baseline_libdir" /opt/lda/fixtures/generic/probe 100)" = "$(LD_LIBRARY_PATH="$candidate_libdir" /opt/lda/fixtures/generic/probe 100)"
    ;;
  python-ctypes|python-cffi|rust-ffi|dlopen-dlsym|c-cpp-source)
    test -n "${LDA_FFI_CHECK_COMMAND:-}"
    bash -lc "$LDA_FFI_CHECK_COMMAND"
    ;;
  debian-relationships)
    for field in Package Version Architecture Depends Provides Conflicts Breaks Replaces; do
      dpkg-deb -f "$(cat /opt/lda/baseline/runtime-deb.path)" "$field" 2>/dev/null >"$tmp/a" || true
      dpkg-deb -f "$(cat /opt/lda/candidate/runtime-deb.path)" "$field" 2>/dev/null >"$tmp/b" || true
      diff -u "$tmp/a" "$tmp/b"
    done
    ;;
  *) exit 64 ;;
esac
printf 'PASS %s\n' "$check"
