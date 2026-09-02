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
OPTS+=(-o "Acquire::Retries=10"
      -o "Acquire::http::Timeout=30"
      -o "Acquire::https::Timeout=30")
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
# When the pinned snapshot service is down and the release archive stands in
# (see prepare-ubuntu-source.sh), ISO-era versions are not what the index
# offers, so alignment becomes best-effort: it is recorded, not enforced.
# Benchmark validity does not rest on it — baseline and candidate are built
# from one source tree in one sandbox and measured interleaved, so the
# installed set is common to both sides of every pair.
# Keep successful downloads and package transactions in this sandbox when the
# snapshot service drops one archive. Re-running apt-get resumes from its cache
# instead of forcing the driver to discard forty minutes of setup work.
aligned=false
for attempt in 1 2 3; do
  # shellcheck disable=SC2046
  if sudo -n apt-get "${OPTS[@]}" install -y --allow-downgrades $(cat "$tmp/requests"); then
    aligned=true
    break
  fi
  echo "snapshot alignment attempt $attempt failed" >&2
  test "$attempt" -eq 3 || sleep $((attempt * 15))
done
if test "$aligned" = true; then
  touch "$marker"
  echo "aligned $count packages to the snapshot"
elif test "${LDA_APT_FALLBACK_USED:-false}" = true; then
  touch "$marker"
  echo "alignment skipped: release-archive fallback cannot reproduce snapshot versions" >&2
else
  echo "alignment against the pinned snapshot remained unavailable after retries" >&2
  # EX_TEMPFAIL: a broken snapshot transport is infrastructure, not a source
  # or candidate failure. The outer driver will preserve state and resume.
  exit 75
fi
