#!/usr/bin/env bash
set -euo pipefail

command="${LDA_PROFILE_COMMAND:-${*:-true}}"
output=/opt/lda/output/profile
mkdir -p "$output"
lscpu >"$output/lscpu.txt"
grep -m1 '^flags' /proc/cpuinfo >"$output/cpuid-flags.txt"
perf stat -x, -r 3 -o "$output/perf-stat.csv" -- sh -lc "$command"
test -s "$output/perf-stat.csv"
perf record --call-graph fp -o "$output/perf.data" -- sh -lc "$command" >/dev/null
perf report --stdio --no-children --sort overhead,symbol -i "$output/perf.data" >"$output/perf-report.txt"
test -s "$output/perf-report.txt"
jq -n \
  --arg command "$command" \
  --arg perf_stat "$(cat "$output/perf-stat.csv")" \
  --arg perf_report "$(cat "$output/perf-report.txt")" \
  '{command:$command,perf_stat:$perf_stat,perf_report:$perf_report}'
