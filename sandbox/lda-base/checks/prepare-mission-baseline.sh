#!/usr/bin/env bash
set -euo pipefail

source_package="${1:?source package required}"
source_version="${2:?source version required}"
shift 2
test "$#" -gt 0 || { echo "at least one binary package required" >&2; exit 64; }

cpu_model="$(lscpu | sed -n 's/^Model name:[[:space:]]*//p')"
case "$cpu_model" in
  *"Xeon"*"6548Y+"*) ;;
  *) echo "LDA benchmark host is not Intel Xeon Gold 6548Y+: $cpu_model" >&2; exit 78 ;;
esac

snapshot="${LDA_BASELINE_APT_SNAPSHOT:-https://snapshot.ubuntu.com/ubuntu/20260825T000000Z}"
apt_root=/opt/lda/apt
download=/opt/lda/source-download
baseline=/opt/lda/baseline
work=/opt/lda/work
sources="$apt_root/snapshot.sources"

case "$snapshot" in https://snapshot.ubuntu.com/ubuntu/*) ;; *) exit 78 ;; esac
sudo mkdir -p "$apt_root/lists/partial" "$apt_root/cache/archives/partial" "$download" "$baseline"
sudo tee "$sources" >/dev/null <<EOF
Types: deb deb-src
URIs: $snapshot
Suites: resolute resolute-updates resolute-security
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
sudo apt-get "${apt_options[@]}" update
sudo rm -rf "$download" "$work" "$baseline"
sudo mkdir -p "$download" "$work" "$baseline"
sudo chown -R "$(id -u):$(id -g)" "$download" "$work" "$baseline"
dpkg-query -W -f='${binary:Package}\t${Version}\t${Architecture}\n' | sort >"$baseline/installed-packages.tsv"

cd "$download"
apt-get "${apt_options[@]}" source --download-only "$source_package=$source_version"
for package in "$@"; do
  apt-get "${apt_options[@]}" download "$package"
done

for package_spec in "$@"; do
  package="${package_spec%%=*}"
  version="${package_spec#*=}"
  matched=0
  for deb in ./*.deb; do
    test -e "$deb" || continue
    test "$(dpkg-deb -f "$deb" Package)" = "$package" || continue
    test "$(dpkg-deb -f "$deb" Version)" = "$version"
    architecture="$(dpkg-deb -f "$deb" Architecture)"
    case "$architecture" in amd64|all) ;; *) exit 78 ;; esac
    declared_source="$(dpkg-deb -f "$deb" Source 2>/dev/null || true)"
    declared_source="${declared_source%% *}"
    test "${declared_source:-$package}" = "$source_package"
    matched=1
  done
  test "$matched" = 1
done

mapfile -t source_files < <(find . -maxdepth 1 -type f \( -name '*.dsc' -o -name '*.orig.tar.*' -o -name '*.debian.tar.*' -o -name '*.diff.gz' \) -printf '%f\n' | sort)
test "${#source_files[@]}" -gt 1
tar --sort=name --mtime=@0 --owner=0 --group=0 --numeric-owner -cf "$baseline/source.tar.bundle" "${source_files[@]}"
cp ./*.deb "$baseline/"
metadata="$baseline/package-metadata.txt"
: >"$metadata"
for package_spec in "$@"; do
  package="${package_spec%%=*}"
  version="${package_spec#*=}"
  printf '=== %s %s ===\n' "$package" "$version" >>"$metadata"
  apt-cache "${apt_options[@]}" show "$package=$version" \
    | sed -n '/^Package:/p;/^Source:/p;/^Version:/p;/^Architecture:/p;/^Depends:/p;/^Pre-Depends:/p;/^Provides:/p;/^Conflicts:/p;/^Breaks:/p;/^Replaces:/p' \
    >>"$metadata"
  apt-get "${apt_options[@]}" --simulate --allow-downgrades install "$package=$version" \
    >>"$metadata"
done

cd "$work"
apt-get "${apt_options[@]}" source "$source_package=$source_version"
source_dir="$(find . -mindepth 1 -maxdepth 1 -type d | head -1)"
test -n "$source_dir"
shopt -s dotglob
mv "$source_dir"/* .
rmdir "$source_dir"
find . -maxdepth 1 -type f \( -name '*.dsc' -o -name '*.tar.*' -o -name '*.diff.gz' \) -delete
sudo apt-get "${apt_options[@]}" build-dep -y --allow-downgrades \
  --allow-change-held-packages .
test "$(dpkg-parsechangelog -S Source)" = "$source_package"
test "$(dpkg-parsechangelog -S Version)" = "$source_version"

git init -b "lda/${source_package}-${source_version}"
git config user.email lda@localhost
git config user.name LDA
git add .
GIT_AUTHOR_DATE=2026-04-23T12:00:00Z GIT_COMMITTER_DATE=2026-04-23T12:00:00Z \
  git commit -m "Ubuntu 26.04 baseline: $source_package $source_version"
git tag lda-baseline
printf '%s=%s\n' "$source_package" "$source_version"
