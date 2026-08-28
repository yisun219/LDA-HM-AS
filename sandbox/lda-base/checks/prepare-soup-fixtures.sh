#!/usr/bin/env bash
# Seeded header-corpus generator for the soup card.
#   LDA_FIXTURE_DIR   target directory (default: the train set)
#   LDA_FIXTURE_SEED  integer seed; varies header CONTENT only, the block
#                     count and class mix stay fixed so iteration counts
#                     remain comparable between fixture sets.
set -euo pipefail
root="${LDA_FIXTURE_DIR:-/opt/lda/fixtures/soup}"
seed="${LDA_FIXTURE_SEED:-2604}"
mkdir -p "$root"
python3 - "$root" "$seed" <<'PY'
import random
import sys
from pathlib import Path

root, seed = Path(sys.argv[1]), int(sys.argv[2])
rng = random.Random(seed)

METHODS = ["GET", "POST", "PUT"]
TYPES = [
    "text/html; charset=utf-8",
    "application/json",
    "application/xml; charset=iso-8859-1",
    "multipart/form-data; boundary={b}",
    "text/plain; charset=utf-8; format=flowed",
]
LANGS = ["en-US", "en", "zh-CN", "de-DE", "fr", "ja-JP", "es-419"]
ENCODINGS = ["gzip", "br", "deflate", "zstd", "identity"]

def quality_list(items, count):
    picked = rng.sample(items, min(count, len(items)))
    parts = []
    for index, item in enumerate(picked):
        if index == 0:
            parts.append(item)
        else:
            parts.append(f"{item};q={round(1.0 - 0.13 * index, 2)}")
    return ", ".join(parts)

blocks = []
for index in range(400):
    boundary = f"b{rng.randrange(1 << 30):08x}"
    lines = [
        f"Host: host-{rng.randrange(4096)}.example.org",
        f"User-Agent: probe/{rng.randrange(9)}.{rng.randrange(30)} (X11; Linux x86_64)",
        f"Accept: {quality_list(['text/html', 'application/xhtml+xml', 'application/json', 'image/avif', 'image/webp', '*/*'], 2 + rng.randrange(4))}",
        f"Accept-Language: {quality_list(LANGS, 2 + rng.randrange(4))}",
        f"Accept-Encoding: {quality_list(ENCODINGS, 2 + rng.randrange(3))}",
        f"Content-Type: {rng.choice(TYPES).format(b=boundary)}",
        f"Cache-Control: max-age={rng.randrange(86400)}, {rng.choice(['public', 'private', 'no-cache'])}",
        f"X-Trace: {rng.randrange(1 << 62):x}",
        f"Cookie: session={rng.randrange(1 << 62):x}; theme={rng.choice(['dark', 'light'])}",
        f"Referer: https://ref-{rng.randrange(512)}.example.org/{rng.randrange(1 << 20):x}",
    ]
    rng.shuffle(lines)
    blocks.append("\n".join(lines))

(root / "headers-corpus.txt").write_text("\n\n".join(blocks) + "\n", encoding="utf-8")
print(f"soup fixtures prepared in {root} seed={seed} blocks={len(blocks)}")
PY
