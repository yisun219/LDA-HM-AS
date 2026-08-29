#!/usr/bin/env bash
# Seeded path/glyph corpus for the cairo-owned micro deck: control points for
# stroking and self-intersecting fills, dash patterns, and text strings. The
# default seed writes the train set; the flow re-runs this with a host-held
# secret seed into a private directory for the hidden holdout.
set -euo pipefail
directory="${LDA_FIXTURE_DIR:-/opt/lda/fixtures/cairo-paths}"
seed="${LDA_FIXTURE_SEED:-20260423}"
mkdir -p "$directory"
python3 - "$directory" "$seed" <<'PY'
import sys

directory, seed = sys.argv[1], int(sys.argv[2])
state = seed * 2654435761 % 2**31 or 1


def rng(bound):
    global state
    state = (1103515245 * state + 12345) % 2**31
    return state % bound


with open(f"{directory}/paths.txt", "w", encoding="utf-8") as stream:
    for _ in range(160):
        points = [f"{rng(4800) / 10.0:.1f}" for _ in range(12)]
        dashes = [f"{rng(140) / 10.0 + 1.0:.1f}" for _ in range(4)]
        stream.write(" ".join(points + dashes) + "\n")

alphabet = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789 .:-"
with open(f"{directory}/strings.txt", "w", encoding="utf-8") as stream:
    for _ in range(48):
        length = rng(28) + 12
        stream.write("".join(alphabet[rng(len(alphabet))] for _ in range(length)) + "\n")
print(f"cairo path fixtures written (seed {seed})")
PY
