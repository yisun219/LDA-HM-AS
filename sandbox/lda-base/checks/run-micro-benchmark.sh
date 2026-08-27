#!/usr/bin/env bash
set -euo pipefail
mode="${1:-candidate}"
if test "$mode" = baseline && test -n "${LDA_MICRO_BASELINE_COMMAND:-}"; then
  exec bash -lc "$LDA_MICRO_BASELINE_COMMAND"
fi
if test "$mode" = candidate && test -n "${LDA_MICRO_BENCHMARK_COMMAND:-}"; then
  exec bash -lc "$LDA_MICRO_BENCHMARK_COMMAND"
fi
case "$mode" in baseline|candidate) ;; *) exit 64 ;; esac
. /opt/lda/harness/checks/libpng-common.sh

# All timing happens inside the sandbox (lda_bench_consumer) so the numbers
# carry no gateway/transport component. LDA_MICRO_FIXTURE_DIR selects an
# alternate PNG set (the hidden holdout); the consumer binary is always the
# canonical, baseline-compiled one.
canonical=/opt/lda/fixtures/libpng
fixdir="${LDA_MICRO_FIXTURE_DIR:-$canonical}"
consumer="$canonical/libpng-consumer"
mult="${LDA_MICRO_ITERATION_MULT:-20}"

for name in boundary small large incompressible; do
  test -f "$fixdir/$name.png" || { echo "missing fixture $fixdir/$name.png" >&2; exit 65; }
done

# Warmup (unmeasured): page cache, dynamic linker, frequency ramp.
lda_run_with_libpng "$mode" "$consumer" "$fixdir/large.png" 2 >/dev/null
lda_run_with_libpng "$mode" "$consumer" "$fixdir/small.png" 200 >/dev/null

lda_bench_consumer micro boundary "$mode" "$fixdir/boundary.png" $((12000 * mult)) "$consumer"
lda_bench_consumer micro small "$mode" "$fixdir/small.png" $((1200 * mult)) "$consumer"
lda_bench_consumer micro large "$mode" "$fixdir/large.png" $((12 * mult)) "$consumer"
lda_bench_consumer micro incompressible "$mode" "$fixdir/incompressible.png" $((36 * mult)) "$consumer"

printf 'micro mode=%s fixdir=%s mult=%s complete\n' "$mode" "$fixdir" "$mult"
