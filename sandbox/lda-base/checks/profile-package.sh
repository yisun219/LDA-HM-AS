#!/usr/bin/env bash
set -euo pipefail

command="${LDA_PROFILE_COMMAND:-${*:-true}}"
output=/opt/lda/output/profile
mkdir -p "$output"
lscpu >"$output/lscpu.txt"
grep -m1 '^flags' /proc/cpuinfo >"$output/cpuid-flags.txt"
perf stat -x, -r 3 -o "$output/perf-stat.csv" -- sh -lc "$command"
test -s "$output/perf-stat.csv"
jq -n --arg command "$command" --arg perf "$(cat "$output/perf-stat.csv")" '{command:$command,perf_stat:$perf}'
