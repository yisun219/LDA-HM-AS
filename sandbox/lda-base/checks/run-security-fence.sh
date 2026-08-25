#!/usr/bin/env bash
set -euo pipefail
if test -n "${LDA_SECURITY_FENCE_COMMAND:-}"; then
  exec bash -lc "$LDA_SECURITY_FENCE_COMMAND"
fi
. /opt/lda/harness/checks/libpng-common.sh
candidate="$(lda_libpng_library candidate)"
readelf -lW "$candidate" | grep -q 'GNU_RELRO'
if readelf -lW "$candidate" | awk '/GNU_STACK/ && $0 ~ /RWE/ {found=1} END {exit found ? 0 : 1}'; then
  echo "candidate has executable stack" >&2
  exit 1
fi
if readelf -dW "$candidate" | grep -Eq 'TEXTREL|RPATH|RUNPATH'; then
  echo "candidate contains TEXTREL, RPATH, or RUNPATH" >&2
  exit 1
fi
readelf -n "$candidate" | grep -q 'Build ID'
printf '%s\n' "ELF hardening invariants passed"
