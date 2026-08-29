#!/usr/bin/env bash
# Seeded identity fixtures for the sssd card: a synthetic user universe and a
# lookup schedule. The universe is installed once at setup; the SCHEDULE is
# the train/holdout axis - a hidden holdout regenerates it from a secret seed
# so a candidate cannot overfit the visible sequence of names and misses.
set -euo pipefail
directory="${LDA_FIXTURE_DIR:-/opt/lda/fixtures/sssd}"
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


# The universe is seed-independent by design: every schedule draws from the
# same installed identities, so holdout regeneration never edits /etc/passwd.
with open(f"{directory}/users.txt", "w", encoding="utf-8") as stream:
    for index in range(3000):
        uid = 20000 + index
        stream.write(
            f"lda_u{index}:x:{uid}:{uid}:LDA synthetic user {index}:"
            "/nonexistent:/usr/sbin/nologin\n"
        )

with open(f"{directory}/schedule.txt", "w", encoding="utf-8") as stream:
    for _ in range(30000):
        if rng(5) == 0:
            stream.write(f"lda_missing{rng(700)}\n")
        else:
            stream.write(f"lda_u{rng(3000)}\n")
print(f"sssd fixtures: universe 3000 users, schedule 30000 lookups, seed {seed}")
PY
