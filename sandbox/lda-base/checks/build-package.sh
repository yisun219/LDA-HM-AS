#!/usr/bin/env bash
# Generic package workbench build: rebuild the prepared source tree as .debs
# for one mode (baseline|candidate) and extract every runtime library so the
# generic fences can compare baseline vs candidate.
#
# Card-provided environment:
#   LDA_PKG_SOURCE    Debian source package name (dpkg-parsechangelog Source)
#   LDA_PKG_VERSION   exact version string
#   LDA_PKG_RUNTIME_DEBS  space-separated binary package names to extract
#                     (runtime libs; dbgsym siblings are pulled when present)
set -euo pipefail

mode="${1:?baseline or candidate required}"
case "$mode" in baseline|candidate) ;; *) exit 64 ;; esac
source_name="${LDA_PKG_SOURCE:?LDA_PKG_SOURCE required}"
version="${LDA_PKG_VERSION:?LDA_PKG_VERSION required}"
runtime_debs="${LDA_PKG_RUNTIME_DEBS:?LDA_PKG_RUNTIME_DEBS required}"

source_root=/opt/lda/work
output_root="/opt/lda/$mode"
package_root="$output_root/root"
package_dir="$output_root/packages"
artifact_schema=1

cd "$source_root"
test "$(dpkg-parsechangelog -S Source)" = "$source_name"
test "$(dpkg-parsechangelog -S Version)" = "$version"
test -z "$(git status --porcelain)" || {
  echo "source worktree must be committed and clean before package build" >&2
  exit 65
}

source_commit="$(git rev-parse HEAD)"
if test -f "$output_root/source-commit" &&
   test "$(cat "$output_root/source-commit")" = "$source_commit" &&
   test -f "$output_root/artifact-schema" &&
   test "$(cat "$output_root/artifact-schema")" = "$artifact_schema"; then
  exit 0
fi

# Clear build outputs only; identity assets under /opt/lda/baseline survive.
rm -rf "$package_root" "$package_dir" \
  "$output_root/source-commit" "$output_root/artifact-schema" \
  "$output_root/libraries.list" "$output_root/runtime-debs.list" \
  "$output_root/upstream-tests-state" "$output_root/upstream-tests-passed" \
  "$output_root/build.log"
mkdir -p "$package_dir" "$package_root"
find /opt/lda -maxdepth 1 -type f \
  \( -name '*.deb' -o -name '*.ddeb' -o -name '*.changes' -o -name '*.buildinfo' \) \
  -delete

build_log="$output_root/build.log"
DEB_BUILD_OPTIONS="parallel=$(nproc)" dpkg-buildpackage -b -uc -us 2>&1 | tee "$build_log"

find /opt/lda -maxdepth 1 -type f \
  \( -name '*.deb' -o -name '*.ddeb' -o -name '*.changes' -o -name '*.buildinfo' \) \
  -exec mv -t "$package_dir" -- {} +

: >"$output_root/runtime-debs.list"
for wanted in $runtime_debs; do
  found=""
  for deb in "$package_dir"/*.deb; do
    if test "$(dpkg-deb -f "$deb" Package)" = "$wanted"; then
      found="$deb"
      break
    fi
  done
  test -n "$found" || { echo "runtime deb $wanted was not built" >&2; exit 66; }
  dpkg-deb -x "$found" "$package_root"
  printf '%s\n' "$found" >>"$output_root/runtime-debs.list"
  for ddeb in "$package_dir"/*.ddeb; do
    test -e "$ddeb" || continue
    if test "$(dpkg-deb -f "$ddeb" Package)" = "$wanted-dbgsym"; then
      dpkg-deb -x "$ddeb" "$package_root"
    fi
  done
done

# Inventory every shared library shipped by the selected runtime debs.
find "$package_root/usr/lib" "$package_root/lib" -type f -name '*.so*' 2>/dev/null \
  | grep -v '/usr/lib/debug/' | LC_ALL=C sort >"$output_root/libraries.list"
test -s "$output_root/libraries.list" || {
  echo "no shared libraries found in $runtime_debs" >&2
  exit 67
}

printf '%s\n' "$source_commit" >"$output_root/source-commit"
printf '%s\n' "$artifact_schema" >"$output_root/artifact-schema"
head -1 "$output_root/runtime-debs.list" | xargs sha256sum >"$output_root/runtime-deb.sha256"
# The upstream-test marker records EVIDENCE, not hope: the build log must
# show dh_auto_test ran, or debian/rules must visibly disable it.
tests_state="no-test-evidence"
if grep -Eq '(^|[[:space:]])dh_auto_test' "$build_log"; then
  tests_state="ran"
elif grep -Eq '^override_dh_auto_test' debian/rules 2>/dev/null &&
     ! sed -n '/^override_dh_auto_test/,/^[^[:space:]#]/p' debian/rules | \
       grep -q 'dh_auto_test'; then
  tests_state="packaging-disables-tests"
fi
printf '%s\n' "$tests_state" >"$output_root/upstream-tests-state"
if test "$tests_state" = no-test-evidence; then
  echo "no evidence the upstream test suite ran, and packaging does not disable it" >&2
  exit 68
fi
touch "$output_root/upstream-tests-passed"

git reset --hard "$source_commit"
git clean -fdx
test -z "$(git status --porcelain)"
