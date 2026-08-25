#!/usr/bin/env bash
set -euo pipefail

mode="${1:?baseline or candidate required}"
case "$mode" in baseline|candidate) ;; *) exit 64 ;; esac

source_root=/opt/lda/work
output_root="/opt/lda/$mode"
package_root="$output_root/root"
package_dir="$output_root/packages"
artifact_schema=2

cd "$source_root"
test "$(dpkg-parsechangelog -S Source)" = libpng1.6
test "$(dpkg-parsechangelog -S Version)" = 1.6.57-1
test -z "$(git status --porcelain)" || {
  echo "source worktree must be committed and clean before package build" >&2
  exit 65
}

source_commit="$(git rev-parse HEAD)"
if test -f "$output_root/source-commit" &&
   test "$(cat "$output_root/source-commit")" = "$source_commit" &&
   test -f "$output_root/libpng16.path" &&
   test -f "$output_root/dev-deb.path" &&
   test -f "$output_root/artifact-schema" &&
   test "$(cat "$output_root/artifact-schema")" = "$artifact_schema"; then
  exit 0
fi

rm -rf "$output_root"
mkdir -p "$package_dir" "$package_root"
find /opt/lda -maxdepth 1 -type f \
  \( -name '*.deb' -o -name '*.ddeb' -o -name '*.changes' -o -name '*.buildinfo' \) \
  -delete

DEB_BUILD_OPTIONS="parallel=$(nproc)" dpkg-buildpackage -b -uc -us

find /opt/lda -maxdepth 1 -type f \
  \( -name '*.deb' -o -name '*.ddeb' -o -name '*.changes' -o -name '*.buildinfo' \) \
  -exec mv -t "$package_dir" -- {} +

runtime_deb=""
dev_deb=""
for deb in "$package_dir"/*.deb; do
  case "$(dpkg-deb -f "$deb" Package)" in
    libpng16-16t64) runtime_deb="$deb" ;;
    libpng-dev) dev_deb="$deb" ;;
  esac
done
test -n "$runtime_deb"
test -n "$dev_deb"
dpkg-deb -x "$runtime_deb" "$package_root"
dpkg-deb -x "$dev_deb" "$package_root"

library="$(find "$package_root/usr/lib" -type f -name 'libpng16.so.16.*' | head -1)"
test -n "$library"
printf '%s\n' "$library" >"$output_root/libpng16.path"
printf '%s\n' "$runtime_deb" >"$output_root/runtime-deb.path"
printf '%s\n' "$dev_deb" >"$output_root/dev-deb.path"
printf '%s\n' "$source_commit" >"$output_root/source-commit"
printf '%s\n' "$artifact_schema" >"$output_root/artifact-schema"
sha256sum "$runtime_deb" >"$output_root/runtime-deb.sha256"
touch "$output_root/upstream-tests-passed"

git reset --hard "$source_commit"
git clean -fdx
test -z "$(git status --porcelain)"
