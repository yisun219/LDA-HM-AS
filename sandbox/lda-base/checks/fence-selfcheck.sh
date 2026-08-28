#!/usr/bin/env bash
# Generic known-bad-sample validation: fence primitives must flag broken
# inputs before any verdict is trusted. Card families add their own probes
# through the card's selfcheck_commands (fence-selfcheck-libpng.sh,
# run-cairo-selfcheck.sh, ...) - a checker that has never flagged a bad
# sample is not trusted with a card.
set -euo pipefail
. /opt/lda/harness/checks/pkg-common.sh

fail() { echo "SELFCHECK FAIL: $*" >&2; exit 1; }
note() { printf 'SELFCHECK %s\n' "$*"; }

lib_a="$(ldconfig -p | awk '/libz\.so\.1 /{print $NF; exit}')"
lib_b="$(ldconfig -p | awk '/libpng16\.so\.16 /{print $NF; exit}')"
test -n "$lib_a" && test -n "$lib_b" || fail "probe libraries unavailable"

# Probe 1: the symbol/ELF ABI comparator must flag two different libraries.
if /opt/lda/harness/checks/abi-fence.sh "$lib_b" "$lib_a" >/dev/null 2>&1; then
  fail "abi comparator accepted a completely different library"
fi
note "abi comparator flags a wrong library"

# Probe 2: abidiff must not accept the wrong pair. On unrelated libraries
# abidiff can hang, so the probe is time-bounded: a refusal or a timeout both
# mean "did not accept"; only exit 0 is the fatal rubber stamp.
command -v abidiff >/dev/null || fail "abidiff is not installed"
if timeout 60 abidiff "$lib_b" "$lib_a" >/dev/null 2>&1; then
  fail "abidiff accepted a completely different library"
fi
note "abidiff does not accept a wrong library"

# Probe 3: the in-sandbox timer must declare a nonce, tag its sample with the
# same nonce, and produce plausible, repeatable A/A readings on a
# deterministic workload.
workdir="$(mktemp -d)"
trap 'rm -rf "$workdir"' EXIT
head -c 4194304 /dev/urandom >"$workdir/fixture"

sample() {
  bash -c '
    set -euo pipefail
    . /opt/lda/harness/checks/pkg-common.sh
    lda_bench_run micro selfcheck baseline 24 \
      sh -c "for i in \$(seq 24); do sha256sum '"$workdir"'/fixture; done | tail -1 | cut -d\" \" -f1"
  '
}

out1="$(sample)"
out2="$(sample)"
hashes=""
for run in 1 2; do
  out="$out1"; test "$run" = 2 && out="$out2"
  nonce="$(printf '%s\n' "$out" | sed -n 's/^LDA_BENCH_NONCE //p' | head -1)"
  test -n "$nonce" || fail "timer did not declare a nonce"
  printf '%s\n' "$out" | grep -q "^LDA_BENCH\[$nonce\] " || \
    fail "timer sample is not tagged with its declared nonce"
  hashes="$hashes $(printf '%s\n' "$out" | sed -n "s/^LDA_BENCH\[$nonce\] //p" | \
    python3 -c 'import json,sys; print(json.load(sys.stdin)["hash"])')"
done
read -r hash1 hash2 <<<"$hashes"
test "$hash1" = "$hash2" || fail "deterministic workload hashed differently across runs"
t1="$(printf '%s\n' "$out1" | sed -n 's/^LDA_BENCH\[[0-9a-f]*\] //p' | \
  python3 -c 'import json,sys; print(json.load(sys.stdin)["seconds"])')"
t2="$(printf '%s\n' "$out2" | sed -n 's/^LDA_BENCH\[[0-9a-f]*\] //p' | \
  python3 -c 'import json,sys; print(json.load(sys.stdin)["seconds"])')"
python3 - "$t1" "$t2" <<'PY'
import sys
a, b = float(sys.argv[1]), float(sys.argv[2])
assert a > 0.01 and b > 0.01, f"timer readings implausibly small: {a} {b}"
ratio = a / b if a > b else b / a
assert ratio < 3.0, f"timer readings unstable: {a} vs {b}"
PY
note "in-sandbox timer declares nonce, tags samples, and is A/A stable"

note "all generic known-bad probes behaved"
