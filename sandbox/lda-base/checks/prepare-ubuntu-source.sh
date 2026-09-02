#!/usr/bin/env bash
set -euo pipefail

package="${1:?Ubuntu source package required}"
version="${2:?exact Ubuntu source version required}"
snapshot="${LDA_BASELINE_APT_SNAPSHOT:?pinned Ubuntu Snapshot URL required}"
work=/opt/lda/work
apt_root=/opt/lda/apt
sources="$apt_root/snapshot.sources"
origin_record="$apt_root/source-origin.json"

case "$snapshot" in
  https://snapshot.ubuntu.com/ubuntu/*) ;;
  *) echo "unsupported APT snapshot: $snapshot" >&2; exit 78 ;;
esac

# The pinned snapshot is the intended package source. When Canonical's snapshot
# service itself is unreachable, the release archive carrying the SAME suite is
# used instead, and the substitution is recorded as provenance. This cannot
# change what gets built: the exact source version is requested by name and
# asserted from the unpacked changelog below, so a fallback mirror either
# serves that exact version or the run fails here.
fallback="${LDA_APT_FALLBACK_MIRROR:-http://archive.ubuntu.com/ubuntu/}"

mkdir -p "$apt_root/lists/partial" "$apt_root/cache/archives/partial"

write_sources() {
  cat >"$sources" <<EOF
Types: deb deb-src
URIs: $1
Suites: resolute
Components: main restricted universe multiverse
Signed-By: /usr/share/keyrings/ubuntu-archive-keyring.gpg
EOF
}

apt_options=(
  -o "Dir::Etc::sourcelist=$sources"
  -o "Dir::Etc::sourceparts=-"
  -o "Dir::State::lists=$apt_root/lists"
  -o "Dir::Cache=$apt_root/cache"
  -o "APT::Get::List-Cleanup=0"
  -o "Acquire::Check-Valid-Until=false"
  -o "Acquire::Retries=10"
  -o "Acquire::http::Timeout=30"
  -o "Acquire::https::Timeout=30"
)

source_index_has_version() {
  apt-cache "${apt_options[@]}" showsrc "$package" 2>/dev/null \
    | awk -v wanted="$version" '
        $1 == "Version:" && $2 == wanted { found = 1 }
        END { exit(found ? 0 : 1) }
      '
}

apt_update() {
  local attempt
  : >"$apt_root/update.log"
  for attempt in 1 2 3; do
    if apt-get "${apt_options[@]}" update >>"$apt_root/update.log" 2>&1 \
        && source_index_has_version; then
      return 0
    fi
    echo "APT index attempt $attempt did not expose $package=$version" \
      >>"$apt_root/update.log"
    if test "$attempt" -lt 3; then
      rm -rf "$apt_root/lists/partial"
      mkdir -p "$apt_root/lists/partial"
      sleep $((attempt * 10))
    fi
  done
  return 1
}

origin="$snapshot"
fallback_used=false
write_sources "$snapshot"
if ! apt_update; then
  echo "pinned APT snapshot unreachable; retrying via release archive $fallback" >&2
  tail -6 "$apt_root/update.log" >&2 || true
  origin="$fallback"
  fallback_used=true
  rm -rf "$apt_root/lists"
  mkdir -p "$apt_root/lists/partial"
  write_sources "$fallback"
  if ! apt_update; then
    echo "both the pinned snapshot and the release archive are unreachable" >&2
    tail -12 "$apt_root/update.log" >&2 || true
    # EX_TEMPFAIL: an upstream package-source outage is infrastructure,
    # never a statement about the candidate.
    exit 75
  fi
fi
printf '{"requested_snapshot":"%s","effective_source":"%s","fallback_used":%s}\n' \
  "$snapshot" "$origin" "$fallback_used" >"$origin_record"
export LDA_APT_FALLBACK_USED="$fallback_used"

/opt/lda/harness/checks/align-to-snapshot.sh

mkdir -p "$work"
cd "$work"
source_fetched=false
for attempt in 1 2 3; do
  find "$work" -mindepth 1 -maxdepth 1 -exec rm -rf -- {} +
  if apt-get "${apt_options[@]}" source "$package=$version"; then
    source_fetched=true
    break
  fi
  echo "source download attempt $attempt failed for $package=$version" >&2
  test "$attempt" -eq 3 || sleep $((attempt * 15))
done
if test "$source_fetched" != true; then
  echo "source download remained unavailable after retries" >&2
  exit 75
fi

source_dir="$(find . -mindepth 1 -maxdepth 1 -type d | head -1)"
test -n "$source_dir"
shopt -s dotglob
mv "$source_dir"/* .
rmdir "$source_dir"

actual_version="$(dpkg-parsechangelog -S Version)"
test "$actual_version" = "$version"

sudo apt-get "${apt_options[@]}" build-dep -y .
find . -maxdepth 1 -type f \( -name '*.dsc' -o -name '*.tar.*' -o -name '*.diff.gz' \) -delete

# Debian versions may contain characters such as '~' and ':' which Git refs
# reject. Keep a readable branch while normalizing the complete package/version
# suffix, then ask Git to validate it before creating the repository.
branch_suffix="$(
  printf '%s-%s' "$package" "$version" \
    | sed -E 's/[^A-Za-z0-9._-]+/_/g; s/\.\.+/_/g; s/^[-.]//; s/[.]$//'
)"
branch="lda/${branch_suffix}-source"
git check-ref-format "refs/heads/$branch"
git init -b "$branch"
git config user.email lda@localhost
git config user.name LDA
# Debian source archives can intentionally contain files matched by upstream
# .gitignore rules. They are still part of the exact buildable baseline.
git add --all --force
snapshot_stamp="${snapshot%/}"
snapshot_stamp="${snapshot_stamp##*/}"
if [[ "$snapshot_stamp" =~ ^([0-9]{4})([0-9]{2})([0-9]{2})T([0-9]{2})([0-9]{2})([0-9]{2})Z$ ]]; then
  git_date="${BASH_REMATCH[1]}-${BASH_REMATCH[2]}-${BASH_REMATCH[3]}T${BASH_REMATCH[4]}:${BASH_REMATCH[5]}:${BASH_REMATCH[6]}Z"
else
  echo "snapshot URL does not contain a deterministic timestamp" >&2
  exit 78
fi
GIT_AUTHOR_DATE="$git_date" GIT_COMMITTER_DATE="$git_date" \
  git commit -m "Ubuntu 26.04 baseline: $package $version"
GIT_COMMITTER_DATE="$git_date" \
  git tag -a lda-baseline -m "Verified Ubuntu baseline $package $version"

printf 'prepared %s=%s from %s (fallback_used=%s)\n' "$package" "$version" "$origin" "$fallback_used"
