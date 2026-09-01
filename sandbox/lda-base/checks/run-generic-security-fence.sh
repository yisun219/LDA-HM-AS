#!/usr/bin/env bash
# ELF hardening invariants over every shared library the candidate ships.
set -euo pipefail
/opt/lda/harness/checks/ensure-pkg-candidate.sh
failures=0
while IFS= read -r library; do
  readelf -lW "$library" | grep -q 'GNU_RELRO' || {
    echo "$library: missing GNU_RELRO" >&2; failures=$((failures+1)); }
  if readelf -lW "$library" | awk '/GNU_STACK/ && $0 ~ /RWE/ {found=1} END {exit found ? 0 : 1}'; then
    echo "$library: executable stack" >&2; failures=$((failures+1))
  fi
  if readelf -dW "$library" | grep -Eq 'TEXTREL|RPATH|RUNPATH'; then
    echo "$library: TEXTREL/RPATH/RUNPATH present" >&2; failures=$((failures+1))
  fi
  readelf -n "$library" | grep -q 'Build ID' || {
    echo "$library: missing Build ID" >&2; failures=$((failures+1)); }
done </opt/lda/candidate/libraries.list
while IFS= read -r library; do
  readelf -lW "$library" | grep -q 'GNU_RELRO' || {
    echo "$library: missing GNU_RELRO" >&2; failures=$((failures+1)); }
  if readelf -lW "$library" | awk '/GNU_STACK/ && $0 ~ /RWE/ {found=1} END {exit found ? 0 : 1}'; then
    echo "$library: executable stack" >&2; failures=$((failures+1));
  fi
  if readelf -dW "$library" | grep -Eq 'TEXTREL|RPATH|RUNPATH'; then
    echo "$library: TEXTREL/RPATH/RUNPATH present" >&2; failures=$((failures+1));
  fi
  readelf -n "$library" | grep -q 'Build ID' || {
    echo "$library: missing Build ID" >&2; failures=$((failures+1)); }
done </opt/lda/candidate/executables.list 2>/dev/null || true
test "$failures" -eq 0
printf 'hardening invariants passed over %s ELF objects\n' "$(( $(wc -l </opt/lda/candidate/libraries.list) + $(wc -l </opt/lda/candidate/executables.list 2>/dev/null || printf 0) ))"
