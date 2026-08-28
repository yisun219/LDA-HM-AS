#!/usr/bin/env bash
set -e
echo probe-start
. /opt/lda/harness/checks/libpng-common.sh

echo "=== gdk-pixbuf loader inventory ==="
ls /usr/lib/x86_64-linux-gnu/gdk-pixbuf-2.0/*/loaders/ 2>/dev/null || echo no-legacy-loaders
dpkg -l | grep -E 'glycin|gdk-pixbuf' | awk '{print $2, $3}'

echo "=== what the pixbuf consumer actually loads ==="
libdir="$(lda_libpng_libdir baseline)"
env LD_LIBRARY_PATH="$libdir" LD_DEBUG=libs \
  /opt/lda/fixtures/libpng/pixbuf-consumer /opt/lda/fixtures/libpng/e2e-deck/deck-00.png 1 \
  2>&1 >/dev/null | grep -oE 'calling init: [^ ]+' | sort -u | grep -E 'glycin|png|pixbuf' || true

echo "=== cairo consumer build (dlopen, no dev headers) ==="
cat > /tmp/cairo-consumer.c <<'C'
#include <dlfcn.h>
#include <stddef.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>

typedef void *(*from_png_fn)(const char *);
typedef unsigned char *(*get_data_fn)(void *);
typedef int (*get_int_fn)(void *);
typedef void (*destroy_fn)(void *);
typedef int (*status_fn)(void *);

static uint64_t hash_bytes(const unsigned char *data, size_t size) {
  uint64_t hash = UINT64_C(1469598103934665603);
  for (size_t i = 0; i < size; ++i) {
    hash ^= data[i];
    hash *= UINT64_C(1099511628211);
  }
  return hash;
}

int main(int argc, char **argv) {
  if (argc < 3) return 64;
  void *cairo = dlopen("libcairo.so.2", RTLD_NOW);
  if (cairo == NULL) { fprintf(stderr, "dlopen: %s\n", dlerror()); return 69; }
  from_png_fn from_png = (from_png_fn)dlsym(cairo, "cairo_image_surface_create_from_png");
  get_data_fn get_data = (get_data_fn)dlsym(cairo, "cairo_image_surface_get_data");
  get_int_fn get_h = (get_int_fn)dlsym(cairo, "cairo_image_surface_get_height");
  get_int_fn get_stride = (get_int_fn)dlsym(cairo, "cairo_image_surface_get_stride");
  status_fn status = (status_fn)dlsym(cairo, "cairo_surface_status");
  destroy_fn destroy = (destroy_fn)dlsym(cairo, "cairo_surface_destroy");
  if (!from_png || !get_data || !get_h || !get_stride || !status || !destroy) {
    fprintf(stderr, "dlsym: %s\n", dlerror());
    return 69;
  }
  const int iterations = atoi(argv[argc - 1]);
  uint64_t aggregate = UINT64_C(1469598103934665603);
  for (int iteration = 0; iteration < iterations; ++iteration) {
    for (int index = 1; index < argc - 1; ++index) {
      void *surface = from_png(argv[index]);
      if (surface == NULL || status(surface) != 0) {
        fprintf(stderr, "cairo png load failed: %d\n", surface ? status(surface) : -1);
        return 2;
      }
      const size_t size = (size_t)get_h(surface) * (size_t)get_stride(surface);
      aggregate = aggregate * UINT64_C(1099511628211) ^ hash_bytes(get_data(surface), size);
      destroy(surface);
    }
  }
  printf("%016llx\n", (unsigned long long)aggregate);
  return 0;
}
C
cc -O2 -Wall -Werror /tmp/cairo-consumer.c -o /tmp/cairo-consumer -ldl
echo cairo-consumer-built

echo "=== cairo attribution ==="
libdir="$(lda_libpng_libdir candidate)"
env LD_LIBRARY_PATH="$libdir" LD_DEBUG=libs \
  /tmp/cairo-consumer /opt/lda/fixtures/libpng/e2e-deck/deck-00.png 1 2>&1 >/dev/null \
  | grep -F "$libdir/libpng16.so.16" >/dev/null && echo cairo-uses-candidate-libpng \
  || { echo CAIRO-NO-ATTRIBUTION; exit 4; }

echo "=== cairo A/B (12 alternated pairs, full deck x4) ==="
deck=(/opt/lda/fixtures/libpng/e2e-deck/deck-*.png)
for pair in 1 2 3 4 5 6 7 8 9 10 11 12; do
  for mode in baseline candidate; do
    libdir="$(lda_libpng_libdir "$mode")"
    s=$(date +%s%N)
    env LD_LIBRARY_PATH="$libdir" /tmp/cairo-consumer "${deck[@]}" 4 >/dev/null
    e=$(date +%s%N)
    echo "CAIRO $mode $(( (e-s)/1000000 ))"
  done
done

echo "=== equivalence across modes ==="
libdir_b="$(lda_libpng_libdir baseline)"; libdir_c="$(lda_libpng_libdir candidate)"
hb="$(env LD_LIBRARY_PATH="$libdir_b" /tmp/cairo-consumer "${deck[@]}" 1)"
hc="$(env LD_LIBRARY_PATH="$libdir_c" /tmp/cairo-consumer "${deck[@]}" 1)"
test "$hb" = "$hc" && echo "pixels-identical $hb" || { echo "PIXELS-DIFFER $hb $hc"; exit 5; }
