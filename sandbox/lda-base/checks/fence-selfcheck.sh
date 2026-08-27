#!/usr/bin/env bash
set -euo pipefail

# Known-bad-sample validation: a checker that has never flagged a broken
# sample is not trusted. Each probe feeds a deliberately wrong input to a
# fence primitive and requires it to fail; a probe that "passes" the bad
# sample fails this whole script.

. /opt/lda/harness/checks/libpng-common.sh

fail() { echo "SELFCHECK FAIL: $*" >&2; exit 1; }
note() { printf 'SELFCHECK %s\n' "$*"; }

baseline_lib="$(lda_libpng_library baseline)"
consumer=/opt/lda/fixtures/libpng/libpng-consumer
fixtures=/opt/lda/fixtures/libpng

# Probe 1: the symbol/ELF ABI comparator must flag a different library.
other_lib="$(ldconfig -p | awk '/libz\.so\.1 /{print $NF; exit}')"
test -n "$other_lib" || fail "no probe library available"
if /opt/lda/harness/checks/abi-fence.sh "$baseline_lib" "$other_lib" >/dev/null 2>&1; then
  fail "abi comparator accepted a completely different library"
fi
note "abi comparator flags a wrong library"

# Probe 2: abidiff must not accept the wrong pair. On unrelated libraries
# abidiff can hang, so the probe is time-bounded: a refusal or a timeout both
# mean "did not accept"; only exit 0 is the fatal rubber stamp.
command -v abidiff >/dev/null || fail "abidiff is not installed"
if timeout 60 abidiff "$baseline_lib" "$other_lib" >/dev/null 2>&1; then
  fail "abidiff accepted a completely different library"
fi
note "abidiff does not accept a wrong library"

# Probe 2b: the fence's real invocation shape (debug dirs + header dirs) must
# complete a self-comparison in bounded time, or the ABI fence cannot work.
baseline_root=/opt/lda/baseline/root
if ! timeout 240 abidiff \
    --d1 "$baseline_root/usr/lib/debug" --d2 "$baseline_root/usr/lib/debug" \
    --headers-dir1 "$baseline_root/usr/include" --headers-dir2 "$baseline_root/usr/include" \
    "$baseline_lib" "$baseline_lib" >/dev/null 2>&1; then
  fail "abidiff cannot complete a debug-informed self-comparison"
fi
note "abidiff self-comparison completes with debug info"

# Probe 3: the behavior hash must be content-sensitive and deterministic.
hash_small_a="$(lda_run_with_libpng baseline "$consumer" "$fixtures/small.png" 3)"
hash_small_b="$(lda_run_with_libpng baseline "$consumer" "$fixtures/small.png" 3)"
hash_large="$(lda_run_with_libpng baseline "$consumer" "$fixtures/large.png" 3)"
test "$hash_small_a" = "$hash_small_b" || fail "behavior hash is not deterministic"
test "$hash_small_a" != "$hash_large" || fail "behavior hash ignores content"
note "behavior hash is deterministic and content-sensitive"

# Probe 4: the in-sandbox timer must produce plausible, repeatable readings.
t1="$(lda_bench_consumer micro selfcheck baseline "$fixtures/small.png" 2000 "$consumer" | sed -n 's/^LDA_BENCH\[[^]]*\] //p' | python3 -c 'import json,sys; print(json.load(sys.stdin)["seconds"])')"
t2="$(lda_bench_consumer micro selfcheck baseline "$fixtures/small.png" 2000 "$consumer" | sed -n 's/^LDA_BENCH\[[^]]*\] //p' | python3 -c 'import json,sys; print(json.load(sys.stdin)["seconds"])')"
python3 - "$t1" "$t2" <<'PY'
import sys
a, b = float(sys.argv[1]), float(sys.argv[2])
assert a > 0.005 and b > 0.005, f"timer readings implausibly small: {a} {b}"
ratio = a / b if a > b else b / a
assert ratio < 3.0, f"timer readings unstable: {a} vs {b}"
PY
note "in-sandbox timer sane (A/A ratio ok)"

note "all known-bad probes behaved"
