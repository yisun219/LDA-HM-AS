#!/usr/bin/env bash
set -euo pipefail

check="${1:?compatibility check name required}"
baseline_root=/opt/lda/baseline/root
candidate_root=/opt/lda/candidate/root
baseline="$(find "$baseline_root/usr/lib" -type f -name 'libpng16.so.16.*' | head -1)"
candidate="$(find "$candidate_root/usr/lib" -type f -name 'libpng16.so.16.*' | head -1)"
test -f "$baseline" && test -f "$candidate"
tmp="$(mktemp -d)"
trap 'rm -rf "$tmp"' EXIT

case "$check" in
  soname)
    test "$(readelf -d "$baseline" | awk '/SONAME/{print $5}')" = "$(readelf -d "$candidate" | awk '/SONAME/{print $5}')"
    ;;
  exported-symbols)
    nm -D --defined-only --format=posix "$baseline" | awk '{print $1,$2}' | sort >"$tmp/a"
    nm -D --defined-only --format=posix "$candidate" | awk '{print $1,$2}' | sort >"$tmp/b"
    diff -u "$tmp/a" "$tmp/b"
    ;;
  symbol-versions)
    readelf --version-info "$baseline" | sed 's/0x[0-9a-fA-F]\+/ADDR/g' >"$tmp/a"
    readelf --version-info "$candidate" | sed 's/0x[0-9a-fA-F]\+/ADDR/g' >"$tmp/b"
    diff -u "$tmp/a" "$tmp/b"
    ;;
  abidiff)
    abidiff --no-added-syms "$baseline" "$candidate"
    ;;
  abi-compliance)
    abi-dumper "$baseline" -o "$tmp/baseline.dump" -lver baseline
    abi-dumper "$candidate" -o "$tmp/candidate.dump" -lver candidate
    abi-compliance-checker -l libpng16 -old "$tmp/baseline.dump" -new "$tmp/candidate.dump"
    ;;
  header-compile)
    printf '#include <png.h>\nint main(void){return PNG_LIBPNG_VER<10000;}\n' >"$tmp/test.c"
    cc -Werror -I"$candidate_root/usr/include/libpng16" "$tmp/test.c" -c -o "$tmp/test.o"
    ;;
  struct-layout)
    printf '#include <png.h>\n#include <stdio.h>\nint main(void){printf("%%zu %%zu\\n",sizeof(png_color),_Alignof(png_color));}\n' >"$tmp/layout.c"
    cc -I"$baseline_root/usr/include/libpng16" "$tmp/layout.c" -o "$tmp/a.out"
    cc -I"$candidate_root/usr/include/libpng16" "$tmp/layout.c" -o "$tmp/b.out"
    test "$("$tmp/a.out")" = "$("$tmp/b.out")"
    ;;
  calling-convention)
    readelf -h "$baseline" | awk -F: '/Class:|Data:|Machine:/{print $1,$2}' >"$tmp/a"
    readelf -h "$candidate" | awk -F: '/Class:|Data:|Machine:/{print $1,$2}' >"$tmp/b"
    diff -u "$tmp/a" "$tmp/b"
    ;;
  pkg-config)
    find "$baseline_root" -path '*pkgconfig/libpng*.pc' -exec sed "s#$baseline_root##g" {} + | sort >"$tmp/a"
    find "$candidate_root" -path '*pkgconfig/libpng*.pc' -exec sed "s#$candidate_root##g" {} + | sort >"$tmp/b"
    diff -u "$tmp/a" "$tmp/b"
    ;;
  cmake-config)
    find "$baseline_root" -iname '*png*cmake*' -o -iname '*png*config*' | sed "s#$baseline_root##" | sort >"$tmp/a"
    find "$candidate_root" -iname '*png*cmake*' -o -iname '*png*config*' | sed "s#$candidate_root##" | sort >"$tmp/b"
    diff -u "$tmp/a" "$tmp/b"
    ;;
  install-paths)
    find "$baseline_root" -type f -o -type l | sed "s#$baseline_root##" | sort >"$tmp/a"
    find "$candidate_root" -type f -o -type l | sed "s#$candidate_root##" | sort >"$tmp/b"
    diff -u "$tmp/a" "$tmp/b"
    ;;
  precompiled-binary)
    /opt/lda/harness/checks/run-ffi-fence.sh
    ;;
  python-ctypes)
    BASELINE="$baseline" CANDIDATE="$candidate" python3 - <<'PY'
import ctypes, os
for name in ("BASELINE", "CANDIDATE"):
    lib = ctypes.CDLL(os.environ[name])
    lib.png_access_version_number.restype = ctypes.c_uint
    assert lib.png_access_version_number() > 0
PY
    ;;
  python-cffi)
    BASELINE="$baseline" CANDIDATE="$candidate" python3 - <<'PY'
import os
from cffi import FFI
ffi=FFI(); ffi.cdef("unsigned int png_access_version_number(void);")
values=[ffi.dlopen(os.environ[name]).png_access_version_number() for name in ("BASELINE","CANDIDATE")]
assert values[0] == values[1]
PY
    ;;
  rust-ffi)
    cat >"$tmp/main.rs" <<'RS'
use std::os::raw::c_uint;
#[link(name="png16")] extern "C" { fn png_access_version_number() -> c_uint; }
fn main(){ unsafe { assert!(png_access_version_number()>0); } }
RS
    rustc "$tmp/main.rs" -L "$(dirname "$candidate")" -o "$tmp/rust-ffi"
    LD_LIBRARY_PATH="$(dirname "$candidate")" "$tmp/rust-ffi"
    ;;
  dlopen-dlsym)
    cat >"$tmp/dlopen.c" <<'C'
#include <dlfcn.h>
#include <stdlib.h>
int main(int argc,char**argv){void*h=dlopen(argv[1],RTLD_NOW);if(!h)return 1;return dlsym(h,"png_access_version_number")?0:2;}
C
    cc "$tmp/dlopen.c" -ldl -o "$tmp/dlopen"
    "$tmp/dlopen" "$candidate"
    ;;
  c-cpp-source)
    printf '#include <png.h>\nint main(){return png_access_version_number()==0;}\n' >"$tmp/c.c"
    printf '#include <png.h>\nint main(){return png_access_version_number()==0;}\n' >"$tmp/cpp.cpp"
    cc -I"$candidate_root/usr/include/libpng16" "$tmp/c.c" "$candidate" -o "$tmp/c"
    c++ -I"$candidate_root/usr/include/libpng16" "$tmp/cpp.cpp" "$candidate" -o "$tmp/cpp"
    "$tmp/c" && "$tmp/cpp"
    ;;
  debian-relationships)
    for field in Package Version Architecture Depends Provides Conflicts Breaks Replaces; do
      dpkg-deb -f "$(cat /opt/lda/baseline/runtime-deb.path)" "$field" 2>/dev/null >"$tmp/a" || true
      dpkg-deb -f "$(cat /opt/lda/candidate/runtime-deb.path)" "$field" 2>/dev/null >"$tmp/b" || true
      diff -u "$tmp/a" "$tmp/b"
    done
    ;;
  *) echo "unknown compatibility check: $check" >&2; exit 64 ;;
esac
printf 'PASS %s\n' "$check"
