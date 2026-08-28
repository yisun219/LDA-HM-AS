#!/usr/bin/env bash
set -euo pipefail

# Fixture generator.
#
# LDA_FIXTURE_DIR   target directory (default: the train set).
# LDA_FIXTURE_SEED  integer seed; varies pixel CONTENT only. Canonical class
#                   geometry (1x1 / 64x64 / 1024x1024 / 512x512) is fixed so
#                   iteration counts stay comparable between fixture sets.
# LDA_FIXTURE_PNGS_ONLY=1  generate only the PNG inputs (used for holdout
#                   sets; the consumer binary and servers are shared).

root="${LDA_FIXTURE_DIR:-/opt/lda/fixtures/libpng}"
seed="${LDA_FIXTURE_SEED:-2604}"
mkdir -p "$root"

python3 - "$root" "$seed" <<'PY'
import random
import sys
from pathlib import Path
from PIL import Image

root = Path(sys.argv[1])
seed = int(sys.argv[2])
rng = random.Random(seed)

# Content parameters derived from the seed. Multipliers are forced odd so
# every fixture set exercises non-trivial pixel variation.
def odd(low, high):
    return rng.randrange(low, high) * 2 + 1

a, b, c = odd(1, 16), odd(1, 16), odd(1, 16)
boundary_pixel = (rng.randrange(256), rng.randrange(256), rng.randrange(256), rng.randrange(256))

def save(name, size, pixels):
    image = Image.new("RGBA", size)
    image.putdata(pixels)
    image.save(root / name, format="PNG", compress_level=6)

save("boundary.png", (1, 1), [boundary_pixel])
save(
    "small.png",
    (64, 64),
    [((x * a) & 255, (y * b) & 255, ((x ^ y) * c) & 255, 255) for y in range(64) for x in range(64)],
)
save(
    "large.png",
    (1024, 1024),
    [((x * a) & 255, (y * b) & 255, ((x + y) * c) & 255, 255) for y in range(1024) for x in range(1024)],
)
save(
    "incompressible.png",
    (512, 512),
    [(rng.randrange(256), rng.randrange(256), rng.randrange(256), 255) for _ in range(512 * 512)],
)

# End-to-end thumbnail deck: distinct full-size images for the GUI-stack
# (gdk-pixbuf) workload, so repeated passes decode varied content.
deck = root / "e2e-deck"
deck.mkdir(exist_ok=True)
for index in range(24):
    image = Image.new("RGBA", (1024, 1024))
    image.putdata(
        [
            (
                ((x * a) + index * 37) & 255,
                ((y * b) ^ (index * 11)) & 255,
                ((x + y + index) * c) & 255,
                255,
            )
            for y in range(1024)
            for x in range(1024)
        ]
    )
    image.save(deck / f"deck-{index:02d}.png", format="PNG", compress_level=6)
PY

if test "${LDA_FIXTURE_PNGS_ONLY:-0}" = 1; then
  printf 'fixtures (pngs only) prepared in %s seed=%s\n' "$root" "$seed"
  exit 0
fi

# GUI-stack consumer: decodes through the real gdk-pixbuf loader pipeline
# (the code path GTK applications use), hashes the decoded pixels, and prints
# one FNV digest. The installed runtime library is bound via dlopen with
# hand-declared prototypes, so no -dev packages are needed and the pinned
# inventory is untouched.
cat >"$root/pixbuf-consumer.c" <<'C'
#include <dlfcn.h>
#include <stddef.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>

typedef struct { uint32_t domain; int code; char *message; } GErrorMin;
typedef void *(*new_from_file_fn)(const char *, GErrorMin **);
typedef unsigned char *(*get_pixels_fn)(void *);
typedef int (*get_int_fn)(void *);
typedef void (*unref_fn)(void *);

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
  void *pixbuf_so = dlopen("libgdk_pixbuf-2.0.so.0", RTLD_NOW | RTLD_GLOBAL);
  if (pixbuf_so == NULL) pixbuf_so = dlopen("libgdk-pixbuf-2.0.so.0", RTLD_NOW | RTLD_GLOBAL);
  void *gobject_so = dlopen("libgobject-2.0.so.0", RTLD_NOW | RTLD_GLOBAL);
  if (pixbuf_so == NULL || gobject_so == NULL) {
    fprintf(stderr, "dlopen failed: %s\n", dlerror());
    return 69;
  }
  new_from_file_fn new_from_file =
      (new_from_file_fn)dlsym(pixbuf_so, "gdk_pixbuf_new_from_file");
  get_pixels_fn get_pixels = (get_pixels_fn)dlsym(pixbuf_so, "gdk_pixbuf_get_pixels");
  get_int_fn get_width = (get_int_fn)dlsym(pixbuf_so, "gdk_pixbuf_get_width");
  get_int_fn get_height = (get_int_fn)dlsym(pixbuf_so, "gdk_pixbuf_get_height");
  get_int_fn get_rowstride = (get_int_fn)dlsym(pixbuf_so, "gdk_pixbuf_get_rowstride");
  unref_fn unref = (unref_fn)dlsym(gobject_so, "g_object_unref");
  if (!new_from_file || !get_pixels || !get_width || !get_height || !get_rowstride || !unref) {
    fprintf(stderr, "dlsym failed: %s\n", dlerror());
    return 69;
  }
  const int iterations = atoi(argv[argc - 1]);
  // Order-sensitive chain: XOR aggregation of a repeated identical value
  // self-cancels on even repetition counts, silently blinding equivalence.
  uint64_t aggregate = UINT64_C(1469598103934665603);
  for (int iteration = 0; iteration < iterations; ++iteration) {
    for (int index = 1; index < argc - 1; ++index) {
      GErrorMin *error = NULL;
      void *pixbuf = new_from_file(argv[index], &error);
      if (pixbuf == NULL) {
        fprintf(stderr, "decode failed: %s\n", error ? error->message : "?");
        return 2;
      }
      const size_t size = (size_t)get_height(pixbuf) * (size_t)get_rowstride(pixbuf);
      aggregate = aggregate * UINT64_C(1099511628211) ^
                  (hash_bytes(get_pixels(pixbuf), size) +
                   (uint64_t)get_width(pixbuf) * 131u + (uint64_t)get_height(pixbuf));
      unref(pixbuf);
    }
  }
  printf("%016llx\n", (unsigned long long)aggregate);
  return 0;
}
C
cc -O2 -Wall -Werror "$root/pixbuf-consumer.c" -o "$root/pixbuf-consumer" -ldl
"$root/pixbuf-consumer" "$root/small.png" 1 >"$root/pixbuf-selftest.txt"

# Cairo consumer: cairo_image_surface_create_from_png is the desktop stack's
# direct libpng path (GTK asset loading, librsvg rasterization, screenshots
# all funnel PNG I/O through cairo). On Ubuntu 26.04 gdk-pixbuf itself
# decodes PNG via glycin (Rust), so cairo is the system-level consumer that
# actually exercises libpng.
cat >"$root/cairo-consumer.c" <<'C'
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
  /* Order-sensitive chain (XOR alone self-cancels on even repeats). */
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
cc -O2 -Wall -Werror "$root/cairo-consumer.c" -o "$root/cairo-consumer" -ldl
"$root/cairo-consumer" "$root/small.png" "$root/small.png" 1 >"$root/cairo-selftest.txt"

cat >"$root/libpng-consumer.c" <<'C'
#include <png.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>

static uint64_t hash_bytes(const unsigned char *data, size_t size) {
  uint64_t hash = UINT64_C(1469598103934665603);
  for (size_t i = 0; i < size; ++i) {
    hash ^= data[i];
    hash *= UINT64_C(1099511628211);
  }
  return hash;
}

int main(int argc, char **argv) {
  if (argc != 3) return 64;
  const int iterations = atoi(argv[2]);
  // Order-sensitive chain: XOR aggregation of a repeated identical value
  // self-cancels on even repetition counts, silently blinding equivalence.
  uint64_t aggregate = UINT64_C(1469598103934665603);
  for (int iteration = 0; iteration < iterations; ++iteration) {
    png_image image;
    image.version = PNG_IMAGE_VERSION;
    image.opaque = NULL;
    if (!png_image_begin_read_from_file(&image, argv[1])) return 2;
    image.format = PNG_FORMAT_RGBA;
    const size_t size = PNG_IMAGE_SIZE(image);
    unsigned char *buffer = malloc(size);
    if (buffer == NULL) return 3;
    if (!png_image_finish_read(&image, NULL, buffer, 0, NULL)) {
      free(buffer);
      return 4;
    }
    aggregate = aggregate * UINT64_C(1099511628211) ^
                (hash_bytes(buffer, size) + (uint64_t)image.width * 131u + image.height);
    free(buffer);
    png_image_free(&image);
  }
  printf("%016llx\n", (unsigned long long)aggregate);
  return 0;
}
C

cc -O2 -Wall -Wextra -Werror "$root/libpng-consumer.c" -o "$root/libpng-consumer" -lpng
"$root/libpng-consumer" "$root/small.png" 1 >"$root/consumer-selftest.txt"

cat >"$root/png-server.py" <<'PY'
import io
import sys
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import parse_qs, urlparse
from PIL import Image

class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        parsed = urlparse(self.path)
        query = parse_qs(parsed.query)
        if parsed.path == "/health":
            payload = b"ok"
            kind = "text/plain"
        elif parsed.path == "/image.png":
            index = int(query.get("id", ["0"])[0])
            image = Image.new("RGBA", (512, 512))
            image.putdata([((x + index) & 255, (y * 3) & 255, (x ^ y ^ index) & 255, 255)
                           for y in range(512) for x in range(512)])
            stream = io.BytesIO()
            image.save(stream, format="PNG", compress_level=6)
            payload = stream.getvalue()
            kind = "image/png"
        else:
            # The round tag propagates into every image URL so a fresh
            # navigation cannot be satisfied from the browser cache.
            tag = query.get("r", ["0"])[0]
            payload = ("<!doctype html><body>" + "".join(
                f'<img src="/image.png?id={i}&r={tag}" width="256" height="256">' for i in range(24)
            ) + "</body>").encode()
            kind = "text/html"
        self.send_response(200)
        self.send_header("Content-Type", kind)
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)
    def log_message(self, *_):
        pass

HTTPServer(("127.0.0.1", int(sys.argv[1])), Handler).serve_forever()
PY

cat >"$root/browser-render.js" <<'JS'
const { chromium } = require('playwright');
(async () => {
  const base = process.argv[2];
  const rounds = parseInt(process.argv[3] || '3', 10);
  const browser = await chromium.launch({headless: true});
  const page = await browser.newPage();
  // Warmup navigation: browser startup, connection setup, JIT. Not measured.
  await page.goto(base + '?r=warmup', {waitUntil: 'networkidle'});
  const renders = [];
  const hashes = [];
  for (let i = 0; i < rounds; i++) {
    await page.goto('about:blank');
    const t0 = process.hrtime.bigint();
    await page.goto(base + '?r=' + i, {waitUntil: 'networkidle'});
    const ready = await page.locator('img').evaluateAll(xs => xs.length === 24 && xs.every(x => x.complete && x.naturalWidth > 0));
    if (!ready) throw new Error('PNG render incomplete');
    const t1 = process.hrtime.bigint();
    renders.push(Number(t1 - t0) / 1e9);
    // Content hash of the actually rendered pixels, computed OUTSIDE the
    // timed window: equivalence must be about what the user saw.
    const hash = await page.evaluate(() => {
      const imgs = Array.from(document.querySelectorAll('img'));
      let h1 = 0x811c9dc5 >>> 0;
      let h2 = 0;
      const canvas = document.createElement('canvas');
      const ctx = canvas.getContext('2d', {willReadFrequently: true});
      for (const img of imgs) {
        canvas.width = img.naturalWidth;
        canvas.height = img.naturalHeight;
        ctx.drawImage(img, 0, 0);
        const data = ctx.getImageData(0, 0, canvas.width, canvas.height).data;
        for (let i = 0; i < data.length; i += 7) {
          h1 = Math.imul((h1 ^ data[i]) >>> 0, 0x01000193) >>> 0;
          h2 = (h2 + data[i]) >>> 0;
        }
      }
      return h1.toString(16) + '-' + h2.toString(16);
    });
    hashes.push(hash);
  }
  console.log(JSON.stringify({renders: renders, hashes: hashes, images: 24}));
  await browser.close();
})();
JS

printf 'fixtures prepared in %s seed=%s\n' "$root" "$seed"
