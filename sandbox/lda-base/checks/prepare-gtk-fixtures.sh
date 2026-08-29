#!/usr/bin/env bash
# Seeded GTK benchmark fixtures: a CSS corpus and a widget-tree seed. The
# default seed writes the train set the Builder may see; the flow re-runs
# this with a host-held secret seed into a private directory for the hidden
# holdout, so the corpus content differs while the shape stays comparable.
set -euo pipefail
directory="${LDA_FIXTURE_DIR:-/opt/lda/fixtures/gtk}"
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


rules = []
for index in range(900):
    a, b = rng(97), rng(89)
    margin, padding, opacity = rng(7) + 1, rng(5) + 1, rng(90) + 1
    top = rng(9) + 1
    rules.append(
        f"box.k{a} frame.m{b} {{ margin: {margin}px; padding: {padding}px; "
        f"opacity: 0.{opacity:02d}; }}"
    )
    rules.append(
        f".k{rng(97)}:hover, .m{rng(89)} > separator {{ margin-top: {top}px; }}"
    )
    if index % 5 == 0:
        rules.append(
            f"box.k{rng(97)} > frame > box > separator {{ min-width: {rng(4) + 1}px; }}"
        )
with open(f"{directory}/corpus.css", "w", encoding="utf-8") as stream:
    stream.write("\n".join(rules) + "\n")
with open(f"{directory}/tree-seed.txt", "w", encoding="utf-8") as stream:
    stream.write(str(seed % 1000003 * 2 + 1) + "\n")
print(f"gtk fixtures: {len(rules)} css rules, seed {seed}")
PY
