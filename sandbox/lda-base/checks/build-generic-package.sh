#!/usr/bin/env bash
set -euo pipefail

mode="${1:?baseline or candidate required}"
runtime_packages="${2:?comma-separated runtime packages required}"
case "$mode" in baseline|candidate) ;; *) exit 64 ;; esac
source_root=/opt/lda/work
output_root="/opt/lda/$mode"
package_root="$output_root/root"
package_dir="$output_root/packages"
cd "$source_root"
test -d .git
test -z "$(git status --porcelain)" || { echo "source must be committed before build" >&2; exit 65; }
source_commit="$(git rev-parse HEAD)"
build_parent="/opt/lda/build/$mode"
sudo mkdir -p /opt/lda/build
sudo chown "$(id -u):$(id -g)" /opt/lda/build
rm -rf "$build_parent"
mkdir -p "$build_parent"
git clone --quiet --no-hardlinks "$source_root" "$build_parent/source"
cd "$build_parent/source"
test "$(git rev-parse HEAD)" = "$source_commit"
sudo mkdir -p "$output_root"
sudo chown "$(id -u):$(id -g)" "$output_root"
rm -rf "$package_root" "$package_dir"
rm -f "$output_root/runtime-debs.list" "$output_root/runtime-deb.path" \
  "$output_root/libraries.list" "$output_root/upstream-tests-passed"
mkdir -p "$package_root" "$package_dir"
find "$build_parent" -maxdepth 1 -type f \( -name '*.deb' -o -name '*.ddeb' -o -name '*.changes' -o -name '*.buildinfo' \) -delete
build_options="parallel=$(nproc)"
if test "${LDA_BUILD_NOCHECK:-0}" = 1; then
  build_options="$build_options nocheck"
fi
set +e
DEB_BUILD_OPTIONS="$build_options" \
DEB_CFLAGS_MAINT_APPEND="${LDA_CFLAGS_APPEND:-}" \
DEB_CXXFLAGS_MAINT_APPEND="${LDA_CXXFLAGS_APPEND:-}" \
DEB_LDFLAGS_MAINT_APPEND="${LDA_LDFLAGS_APPEND:-}" \
dpkg-buildpackage -b -uc -us \
  >"$output_root/build.stdout" 2>"$output_root/build.stderr"
build_exit=$?
set -e
if test "$build_exit" -ne 0; then
  tail -n 200 "$output_root/build.stdout" >&2 || true
  tail -n 200 "$output_root/build.stderr" >&2 || true
  find . -type f \( -name 'testlog.txt' -o -name 'meson-logs.txt' \) -print -exec tail -n 200 {} \; >&2 || true
  exit "$build_exit"
fi
find "$build_parent" -maxdepth 1 -type f \( -name '*.deb' -o -name '*.ddeb' -o -name '*.changes' -o -name '*.buildinfo' \) -exec mv -t "$package_dir" -- {} +
IFS=, read -ra wanted <<<"$runtime_packages"
runtime_debs=()
for deb in "$package_dir"/*.deb; do
  package="$(dpkg-deb -f "$deb" Package)"
  for expected in "${wanted[@]}"; do
    if test "$package" = "$expected"; then
      runtime_debs+=("$deb")
      dpkg-deb -x "$deb" "$package_root"
    fi
  done
done
test "${#runtime_debs[@]}" -gt 0
printf '%s\n' "${runtime_debs[@]}" >"$output_root/runtime-debs.list"
printf '%s\n' "${runtime_debs[0]}" >"$output_root/runtime-deb.path"
find "$package_root/usr/lib" -type f -name '*.so.*' | sort >"$output_root/libraries.list"
test -s "$output_root/libraries.list"
touch "$output_root/build-completed"
if test "${LDA_BUILD_NOCHECK:-0}" != 1; then
  touch "$output_root/upstream-tests-passed"
fi
rm -rf "$build_parent"
test -z "$(git -C "$source_root" status --porcelain)"
