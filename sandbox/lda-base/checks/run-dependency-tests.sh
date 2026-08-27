#!/usr/bin/env bash
set -euo pipefail
. /opt/lda/harness/checks/libpng-common.sh
fixture=/opt/lda/fixtures/libpng/large.png
libdir="$(lda_libpng_libdir candidate)"
env LD_LIBRARY_PATH="$libdir" python3 - "$fixture" <<'PY'
import sys
from PIL import Image
with Image.open(sys.argv[1]) as image:
    image.load()
    assert image.size == (1024, 1024)
    assert image.mode == "RGBA"
PY
tmp="$(mktemp -d)"
trap 'rm -rf "$tmp"' EXIT
env LD_LIBRARY_PATH="$libdir" LD_DEBUG=libs \
  gdk-pixbuf-csource --raw --static --name=lda_fixture "$fixture" \
  >"$tmp/fixture.c" 2>"$tmp/loader.log"
test -s "$tmp/fixture.c"
grep -F "$libdir/libpng16.so.16" "$tmp/loader.log" >/dev/null
printf '%s\n' "Pillow and gdk-pixbuf consumers passed"
