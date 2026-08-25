#!/usr/bin/env bash
set -euo pipefail

package="${1:?Ubuntu source package required}"
version="${2:-}"
if test "${LDA_BASELINE_MODE:-source_package}" = iso_snapshot; then
  echo "iso_snapshot requires a pre-provisioned, versioned source artifact; refusing live APT source setup" >&2
  exit 78
fi
cd /opt/lda
if grep -Rqs '^Types: deb$' /etc/apt/sources.list.d; then
  sed -i 's/^Types: deb$/Types: deb deb-src/' /etc/apt/sources.list.d/*.sources
fi
apt-get update
rm -rf /opt/lda/work
mkdir -p /opt/lda/work
cd /opt/lda/work
if test -n "$version"; then
  apt-get source "$package=$version"
else
  apt-get source "$package"
fi
source_dir=$(find . -mindepth 1 -maxdepth 1 -type d | head -1)
test -n "$source_dir"
shopt -s dotglob
mv "$source_dir"/* .
rmdir "$source_dir"
git init
git config user.email lda@localhost
git config user.name LDA
git add .
git commit -m "Ubuntu 26.04 baseline: $package"
