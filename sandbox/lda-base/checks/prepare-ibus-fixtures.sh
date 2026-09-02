#!/usr/bin/env bash
# Seeded ibus fixtures: a component corpus (registry input) and a key-event
# script (session input). Holdout = another seed into another directory.
set -euo pipefail
directory="${LDA_FIXTURE_DIR:-/opt/lda/fixtures/ibus}"
seed="${LDA_FIXTURE_SEED:-20260423}"
mkdir -p "$directory/components"
python3 - "$directory" "$seed" <<'PY'
import sys
directory, seed = sys.argv[1], int(sys.argv[2])
state = seed * 2654435761 % 2**31 or 1
def rng(bound):
    global state
    state = (1103515245 * state + 12345) % 2**31
    return state % bound
langs = ["en", "de", "fr", "es", "ja", "zh_CN", "ko", "ru", "ar", "hi", "pt", "it"]
layouts = ["us", "de", "fr", "es", "jp", "kr", "ru", "ara", "in", "br", "it", "default"]
words = ["Anthos", "Bora", "Cirrus", "Delta", "Echo", "Fjord", "Gamma", "Helix", "Iota", "Juno", "Kappa", "Lumen", "Mesa", "Nova", "Orbit", "Pico"]
components = 220 + rng(80)
engines_total = 0
for c in range(components):
    lines = ['<?xml version="1.0" encoding="utf-8"?>', "<component>",
             f"<name>org.freedesktop.IBus.LDA{c}</name>", f"<description>LDA synthetic component {c}</description>",
             f"<exec>/usr/libexec/ibus-engine-lda{c} --ibus</exec>", f"<version>1.{rng(9)}.{rng(20)}</version>",
             "<author>LDA</author>", "<license>GPL</license>", "<homepage>https://example.invalid/lda</homepage>",
             f"<textdomain>lda{c}</textdomain>", "<engines>"]
    n = 24 + rng(28)
    for e in range(n):
        lang = langs[rng(len(langs))]; layout = layouts[rng(len(layouts))]
        name = f"lda{c}-{words[rng(len(words))].lower()}{e}"
        lines += ["<engine>", f"<name>{name}</name>", f"<language>{lang}</language>", f"<license>GPL</license>",
                  f"<author>LDA {words[rng(len(words))]}</author>", f"<icon>ibus-lda-{rng(50)}</icon>",
                  f"<layout>{layout}</layout>", f"<longname>{words[rng(len(words))]} {words[rng(len(words))]} {e}</longname>",
                  f"<description>Synthetic engine {name} for {lang} on {layout}, rank {rng(100)}</description>",
                  f"<rank>{rng(100)}</rank>", f"<symbol>{chr(0x4e00 + rng(400))}</symbol>",
                  f"<setup>/usr/libexec/ibus-setup-lda{c} --engine {name}</setup>",
                  f"<hotkeys>Control+space,Super+{chr(97 + rng(26))}</hotkeys>",
                  f"<textdomain>lda{c}</textdomain>", "</engine>"]
        engines_total += 1
    lines += ["</engines>", "</component>"]
    with open(f"{directory}/components/lda{c}.xml", "w", encoding="utf-8") as stream:
        stream.write("\n".join(lines) + "\n")
# Key script: keyval keycode state, US layout letters plus dead-key compose
# sequences (dead_acute + vowel) handled by the simple engine.
keys = []
letters = "abcdefghijklmnopqrstuvwxyz"
dead_acute, vowels = 0xfe51, "aeiou"
for i in range(600):
    r = rng(10)
    if r < 7:
        ch = letters[rng(26)]; keys.append((ord(ch), 0, 0))
    elif r < 9:
        keys.append((dead_acute, 0, 0)); keys.append((ord(vowels[rng(5)]), 0, 0))
    else:
        keys.append((0x20, 0, 0))
with open(f"{directory}/keys.txt", "w", encoding="utf-8") as stream:
    stream.write("\n".join(f"{a} {b} {c}" for a, b, c in keys) + "\n")
with open(f"{directory}/params.env", "w", encoding="utf-8") as stream:
    stream.write(f"IBUS_FIXTURE_SEED={seed}\nIBUS_COMPONENTS={components}\nIBUS_ENGINES={engines_total}\n")
print(f"ibus fixtures: {components} components, {engines_total} engines, {len(keys)} keys, seed {seed}")
PY
