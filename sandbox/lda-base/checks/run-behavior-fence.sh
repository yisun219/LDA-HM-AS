#!/usr/bin/env bash
set -euo pipefail
. /opt/lda/harness/checks/libpng-common.sh
consumer=/opt/lda/fixtures/libpng/libpng-consumer
for fixture in /opt/lda/fixtures/libpng/{boundary,small,large,incompressible}.png; do
  baseline="$(lda_run_with_libpng baseline "$consumer" "$fixture" 1)"
  candidate="$(lda_run_with_libpng candidate "$consumer" "$fixture" 1)"
  test "$baseline" = "$candidate"
  printf '%s %s\n' "$(basename "$fixture")" "$candidate"
done

# Anti-memoization probe: repeated decodes of one fixture must scale roughly
# linearly with the iteration count. A candidate that caches "same input ->
# same decoded output" would collapse the repeated-decode micro benchmark
# into a lookup, a "gain" that generalizes to nothing; that is a behavior
# change and is refused here mechanically.
large=/opt/lda/fixtures/libpng/large.png
t_one_ns=0
for _ in 1 2 3; do
  start="$(date +%s%N)"
  lda_run_with_libpng candidate "$consumer" "$large" 1 >/dev/null
  end="$(date +%s%N)"
  sample=$((end - start))
  if test "$t_one_ns" -eq 0 || test "$sample" -lt "$t_one_ns"; then
    t_one_ns=$sample
  fi
done
start="$(date +%s%N)"
lda_run_with_libpng candidate "$consumer" "$large" 64 >/dev/null
end="$(date +%s%N)"
t_many_ns=$((end - start))
scaling="$(awk -v one="$t_one_ns" -v many="$t_many_ns" 'BEGIN{printf "%.2f", many / one}')"
awk -v s="$scaling" 'BEGIN{exit !(s >= 20.0)}' || {
  echo "iteration scaling collapsed: 64 decodes took only ${scaling}x one decode (memoization?)" >&2
  exit 1
}
printf 'iteration scaling ok: 64 decodes = %sx one decode\n' "$scaling"
