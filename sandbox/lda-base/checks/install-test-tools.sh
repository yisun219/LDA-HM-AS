#!/usr/bin/env bash
# Install the test tooling (autopkgtest) from the pinned snapshot, and point
# the system apt at the same snapshot so test dependencies resolve
# deterministically instead of from a mutable mirror.
set -euo pipefail
apt_root=/opt/lda/apt
sources="$apt_root/snapshot.sources"
test -s "$sources" || {
  echo "snapshot sources missing; run prepare-ubuntu-source.sh first" >&2
  exit 78
}
if ! test -f /etc/apt/sources.list.d/lda-snapshot.sources; then
  sudo -n cp "$sources" /etc/apt/sources.list.d/lda-snapshot.sources
  for original in /etc/apt/sources.list.d/ubuntu.sources /etc/apt/sources.list; do
    if test -f "$original"; then
      sudo -n mv "$original" "/etc/apt/lda-disabled-$(basename "$original")"
    fi
  done
  sudo -n apt-get -o Acquire::Check-Valid-Until=false update
fi
if ! command -v autopkgtest >/dev/null; then
  sudo -n apt-get -o Acquire::Check-Valid-Until=false install -y autopkgtest
fi
test -x "$(command -v autopkgtest)"
# Profiling: on Ubuntu 26.04 the perf binary ships in linux-perf (not in
# linux-tools-*). Software sampling (cpu-clock) is what the Firecracker guest
# supports - there is no PMU - and that is what the Builder profiles with.
if ! command -v perf >/dev/null; then
  sudo -n apt-get -o Acquire::Check-Valid-Until=false install -y --no-install-recommends linux-perf \
    || echo "linux-perf unavailable from the snapshot; profiling falls back to the Builder's own tooling" >&2
fi
echo "autopkgtest ready; perf: $(command -v perf || echo absent); system apt pinned to the recorded snapshot"
