#!/usr/bin/env bash
set -euo pipefail

package="${1:?Ubuntu source package required}"
version="${2:?exact Ubuntu source version required}"
snapshot="${LDA_BASELINE_APT_SNAPSHOT:?pinned Ubuntu Snapshot URL required}"
work=/opt/lda/work
apt_root=/opt/lda/apt
sources="$apt_root/snapshot.sources"

case "$snapshot" in
  https://snapshot.ubuntu.com/ubuntu/*) ;;
  *) echo "unsupported APT snapshot: $snapshot" >&2; exit 78 ;;
esac

mkdir -p "$apt_root/lists/partial" "$apt_root/cache/archives/partial"
cat >"$sources" <<EOF
Types: deb deb-src
URIs: $snapshot
Suites: resolute
Components: main restricted universe multiverse
Signed-By: /usr/share/keyrings/ubuntu-archive-keyring.gpg
EOF

apt_options=(
  -o "Dir::Etc::sourcelist=$sources"
  -o "Dir::Etc::sourceparts=-"
  -o "Dir::State::lists=$apt_root/lists"
  -o "Dir::Cache=$apt_root/cache"
  -o "APT::Get::List-Cleanup=0"
  -o "Acquire::Check-Valid-Until=false"
)

apt-get "${apt_options[@]}" update

mkdir -p "$work"
find "$work" -mindepth 1 -maxdepth 1 -exec rm -rf -- {} +
cd "$work"
apt-get "${apt_options[@]}" source "$package=$version"

source_dir="$(find . -mindepth 1 -maxdepth 1 -type d | head -1)"
test -n "$source_dir"
shopt -s dotglob
mv "$source_dir"/* .
rmdir "$source_dir"

actual_version="$(dpkg-parsechangelog -S Version)"
test "$actual_version" = "$version"

sudo apt-get "${apt_options[@]}" build-dep -y .
find . -maxdepth 1 -type f \( -name '*.dsc' -o -name '*.tar.*' -o -name '*.diff.gz' \) -delete

git init -b lda/libpng-1.6.57-1
git config user.email lda@localhost
git config user.name LDA
git add .
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

printf 'prepared %s=%s from %s\n' "$package" "$version" "$snapshot"
