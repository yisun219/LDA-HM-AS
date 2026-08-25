#!/usr/bin/env bash
set -euo pipefail

baseline="${1:?baseline library required}"
candidate="${2:?candidate library required}"
abidiff --no-added-syms --no-show-locs "$baseline" "$candidate"
