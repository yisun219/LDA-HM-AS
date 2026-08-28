#!/usr/bin/env bash
# Align every installed package to the pinned snapshot's index version, so
# build-deps and stock package installs resolve exactly as they would on an
# ISO-era system. The template carries later security updates than the
# recorded snapshot, and the apt solver refuses to downgrade automatically;
# an explicit pkg=version request is the one downgrade it honors, so the
# drifted set is computed and requested outright. Idempotent per sandbox.
set -euo pipefail
apt_root=/opt/lda/apt
sources="$apt_root/snapshot.sources"
test -s "$sources" || { echo "snapshot sources missing; write them first" >&2; exit 78; }
marker="$apt_root/.aligned-to-snapshot"
if test -f "$marker"; then
  echo "already aligned to snapshot"
  exit 0
fi
OPTS=(-o "Dir::Etc::sourcelist=$sources" -o "Dir::Etc::sourceparts=-"
      -o "Dir::State::lists=$apt_root/lists" -o "Dir::Cache=$apt_root/cache"
      -o "APT::Get::List-Cleanup=0" -o "Acquire::Check-Valid-Until=false")
tmp="$(mktemp -d)"
trap 'rm -rf "$tmp"' EXIT
dpkg-query -W -f='${Package} ${Version}\n' | sort >"$tmp/installed"
awk '{print $1}' "$tmp/installed" \
  | xargs apt-cache "${OPTS[@]}" madison 2>/dev/null \
  | awk '$0 !~ /Sources$/ {gsub(/ /, "", $1); print $1, $3}' \
  | sort -u -k1,1 >"$tmp/snapshot"
join "$tmp/installed" "$tmp/snapshot" \
  | awk '$2 != $3 {print $1 "=" $3}' >"$tmp/requests"
count="$(wc -l <"$tmp/requests")"
if test "$count" -eq 0; then
  echo "no version drift against the snapshot"
  touch "$marker"
  exit 0
fi
echo "aligning $count installed packages to snapshot versions"
# shellcheck disable=SC2046
sudo -n apt-get "${OPTS[@]}" install -y --allow-downgrades $(cat "$tmp/requests")
touch "$marker"
echo "aligned $count packages to the snapshot"
