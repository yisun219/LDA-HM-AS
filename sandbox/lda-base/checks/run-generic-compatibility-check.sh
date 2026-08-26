#!/usr/bin/env bash
set -euo pipefail
check="${1:?check required}"
baseline_root=/opt/lda/baseline/root
candidate_root=/opt/lda/candidate/root
tmp="$(mktemp -d)"
trap 'rm -rf "$tmp"' EXIT
pkg_args=()
if test -n "${LDA_PKG_CONFIG_MODULES:-}"; then
  IFS=, read -ra requested_modules <<<"$LDA_PKG_CONFIG_MODULES"
  read -ra pkg_args <<<"$(pkg-config --cflags --libs "${requested_modules[@]}")"
fi
mapfile -t baseline_libraries </opt/lda/baseline/libraries.list
mapfile -t candidate_libraries </opt/lda/candidate/libraries.list
test "${#baseline_libraries[@]}" = "${#candidate_libraries[@]}"

normalize_library() { basename "$1" | sed -E 's/\.so\..*/.so/'; }
pair_for() {
  local baseline="$1" relative candidate
  relative="${baseline#$baseline_root/}"
  candidate="$candidate_root/$relative"
  test -f "$candidate"
  printf '%s\n' "$candidate"
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
          readelf --dyn-syms --wide "$baseline" | awk '$7 != "UND" && $8 != "" {print $4,$5,$6,$8}' | sort >"$tmp/a"
          readelf --dyn-syms --wide "$candidate" | awk '$7 != "UND" && $8 != "" {print $4,$5,$6,$8}' | sort >"$tmp/b"
          diff -u "$tmp/a" "$tmp/b" ;;
        abidiff) abidiff --no-added-syms "$baseline" "$candidate" ;;
        abi-compliance)
          relative="${baseline#$baseline_root/}"
          rebuild="/opt/lda/baseline/rebuild-root/$relative"
          test -f "$rebuild"
          abi-dumper "$rebuild" -o "$tmp/a.dump" -lver baseline -search-debuginfo "/opt/lda/baseline/rebuild-root/usr/lib/debug"
          abi-dumper "$candidate" -o "$tmp/b.dump" -lver candidate -search-debuginfo "$candidate_root/usr/lib/debug"
          abi-compliance-checker -l "$(normalize_library "$baseline")" -old "$tmp/a.dump" -new "$tmp/b.dump" ;;
      esac
    done
    ;;
  header-compile)
    test -n "${LDA_PUBLIC_HEADER:-}"
    printf '#include <%s>\nint main(void){return 0;}\n' "$LDA_PUBLIC_HEADER" >"$tmp/test.c"
    includes=(); while IFS= read -r directory; do includes+=("-I$directory"); done < <(find "$candidate_root/usr/include" -type d | sort)
    cc -Werror "${includes[@]}" "${pkg_args[@]}" "$tmp/test.c" -c -o "$tmp/test.o"
    ;;
  struct-layout)
    test -n "${LDA_LAYOUT_BODY:-}"
    printf '#include <%s>\n#include <stdio.h>\nint main(void){%s}\n' "$LDA_PUBLIC_HEADER" "$LDA_LAYOUT_BODY" >"$tmp/layout.c"
    for mode in baseline candidate; do
      root="/opt/lda/$mode/root"; includes=(); while IFS= read -r directory; do includes+=("-I$directory"); done < <(find "$root/usr/include" -type d | sort)
      cc "${includes[@]}" "${pkg_args[@]}" "$tmp/layout.c" -o "$tmp/$mode"
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
      if test "$check" = install-paths; then
        find "$root" -path "$pattern" \( -type f -o -type l \) | sed "s#$root##" | sort
      else
        while IFS= read -r path; do
          relative="${path#$root}"
          if test -L "$path"; then
            printf 'LINK %s %s\n' "$relative" "$(readlink "$path")"
          else
            printf 'FILE %s %s\n' "$relative" "$(sha256sum "$path" | cut -d' ' -f1)"
          fi
        done < <(find "$root" -path "$pattern" \( -type f -o -type l \) | sort)
      fi >"$tmp/$mode"
    done
    diff -u "$tmp/baseline" "$tmp/candidate"
    ;;
  ldconfig)
    for mode in baseline candidate; do
      root="/opt/lda/$mode/root"
      sudo mkdir -p "$root/etc"
      find "$root/usr/lib" -type d | sed "s#$root##" | sort -u | sudo tee "$root/etc/ld.so.conf" >/dev/null
      sudo ldconfig -r "$root"
      sudo ldconfig -r "$root" -p | sed '1d' | sort >"$tmp/$mode"
    done
    diff -u "$tmp/baseline" "$tmp/candidate"
    ;;
  precompiled-binary)
    baseline_libdir="$(dirname "$(head -1 /opt/lda/baseline/libraries.list)")"
    candidate_libdir="$(dirname "$(head -1 /opt/lda/candidate/libraries.list)")"
    test "$(LD_LIBRARY_PATH="$baseline_libdir" /opt/lda/fixtures/generic/probe 100)" = "$(LD_LIBRARY_PATH="$candidate_libdir" /opt/lda/fixtures/generic/probe 100)"
    ;;
  python-ctypes)
    library="$(head -1 /opt/lda/candidate/libraries.list)"
    python3 - "$library" <<'PY'
import ctypes, sys
ctypes.CDLL(sys.argv[1])
PY
    ;;
  python-cffi)
    library="$(head -1 /opt/lda/candidate/libraries.list)"
    python3 - "$library" <<'PY'
import cffi, sys
cffi.FFI().dlopen(sys.argv[1])
PY
    ;;
  rust-ffi)
    library="$(head -1 /opt/lda/candidate/libraries.list)"
    cat >"$tmp/dlopen.rs" <<'RS'
use std::env;
use std::ffi::CString;
use std::os::raw::{c_char, c_int, c_void};
#[link(name="dl")]
extern "C" { fn dlopen(name: *const c_char, flags: c_int) -> *mut c_void; fn dlclose(handle: *mut c_void) -> c_int; }
fn main() {
    let path = CString::new(env::args().nth(1).unwrap()).unwrap();
    let handle = unsafe { dlopen(path.as_ptr(), 1) };
    assert!(!handle.is_null());
    unsafe { dlclose(handle); }
}
RS
    rustc "$tmp/dlopen.rs" -o "$tmp/rust-dlopen"
    "$tmp/rust-dlopen" "$library"
    ;;
  dlopen-dlsym)
    library="$(head -1 /opt/lda/candidate/libraries.list)"
    cat >"$tmp/dlopen.c" <<'C'
#include <dlfcn.h>
int main(int argc, char **argv) { void *h = dlopen(argv[1], RTLD_LAZY | RTLD_LOCAL); if (!h) return 1; return dlclose(h); }
C
    cc -Werror "$tmp/dlopen.c" -ldl -o "$tmp/dlopen"
    "$tmp/dlopen" "$library"
    ;;
  c-cpp-source)
    test -n "${LDA_LINK_LIBRARIES:-}"
    includes=(); while IFS= read -r directory; do includes+=("-I$directory"); done < <(find "$candidate_root/usr/include" -type d | sort)
    lib_args=(); while IFS= read -r directory; do lib_args+=("-L$directory" "-Wl,-rpath-link,$directory"); done < <(find "$candidate_root/usr/lib" -type d | sort)
    read -ra requested_libraries <<<"$LDA_LINK_LIBRARIES"
    cp /opt/lda/fixtures/generic/probe.c "$tmp/probe.c"
    cp /opt/lda/fixtures/generic/probe.c "$tmp/probe.cc"
    cc -O2 -Werror "${includes[@]}" "$tmp/probe.c" "${lib_args[@]}" "${pkg_args[@]}" "${requested_libraries[@]}" -o "$tmp/probe-c"
    c++ -O2 -Werror "${includes[@]}" "$tmp/probe.cc" "${lib_args[@]}" "${pkg_args[@]}" "${requested_libraries[@]}" -o "$tmp/probe-cpp"
    candidate_libdir="$(dirname "$(head -1 /opt/lda/candidate/libraries.list)")"
    test "$(LD_LIBRARY_PATH="$candidate_libdir" "$tmp/probe-c" 100)" = "$(cat /opt/lda/fixtures/generic/baseline-output)"
    test "$(LD_LIBRARY_PATH="$candidate_libdir" "$tmp/probe-cpp" 100)" = "$(cat /opt/lda/fixtures/generic/baseline-output)"
    ;;
  debian-relationships)
    while IFS= read -r baseline_deb; do
      package="$(dpkg-deb -f "$baseline_deb" Package)"
      candidate_deb=""
      while IFS= read -r possible; do
        if test "$(dpkg-deb -f "$possible" Package)" = "$package"; then candidate_deb="$possible"; break; fi
      done </opt/lda/candidate/runtime-debs.list
      test -n "$candidate_deb"
      for field in Package Version Architecture Depends Pre-Depends Provides Conflicts Breaks Replaces; do
        dpkg-deb -f "$baseline_deb" "$field" 2>/dev/null >"$tmp/a" || true
        dpkg-deb -f "$candidate_deb" "$field" 2>/dev/null >"$tmp/b" || true
        diff -u "$tmp/a" "$tmp/b"
      done
    done </opt/lda/baseline/runtime-debs.list
    test "$(wc -l </opt/lda/baseline/runtime-debs.list)" = "$(wc -l </opt/lda/candidate/runtime-debs.list)"
    ;;
  *) exit 64 ;;
esac
printf 'PASS %s\n' "$check"
