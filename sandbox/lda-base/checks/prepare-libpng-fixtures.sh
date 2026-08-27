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
PY

if test "${LDA_FIXTURE_PNGS_ONLY:-0}" = 1; then
  printf 'fixtures (pngs only) prepared in %s seed=%s\n' "$root" "$seed"
  exit 0
fi

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
  uint64_t aggregate = 0;
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
    aggregate ^= hash_bytes(buffer, size) + (uint64_t)image.width * 131u + image.height;
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
  for (let i = 0; i < rounds; i++) {
    await page.goto('about:blank');
    const t0 = process.hrtime.bigint();
    await page.goto(base + '?r=' + i, {waitUntil: 'networkidle'});
    const ready = await page.locator('img').evaluateAll(xs => xs.length === 24 && xs.every(x => x.complete && x.naturalWidth > 0));
    if (!ready) throw new Error('PNG render incomplete');
    const t1 = process.hrtime.bigint();
    renders.push(Number(t1 - t0) / 1e9);
  }
  console.log(JSON.stringify({renders: renders, images: 24}));
  await browser.close();
})();
JS

printf 'fixtures prepared in %s seed=%s\n' "$root" "$seed"
