#!/usr/bin/env bash
set -euo pipefail

mode="${LDA_BASELINE_MODE:-source_package}"
expected_release="${LDA_BASELINE_RELEASE:-26.04}"
expected_codename="${LDA_BASELINE_CODENAME:-resolute}"
expected_arch="${LDA_BASELINE_ARCH:-amd64}"

. /etc/os-release
test "${VERSION_ID:-}" = "$expected_release"
test "${VERSION_CODENAME:-${UBUNTU_CODENAME:-}}" = "$expected_codename"
test "$(dpkg --print-architecture)" = "$expected_arch"

if test "$mode" = source_package; then
  printf '%s\n' "source_package baseline verified: Ubuntu $expected_release/$expected_codename $expected_arch"
  exit 0
fi

test "$mode" = iso_snapshot
metadata="${LDA_BASELINE_METADATA_PATH:?baseline metadata path required}"
manifest="${LDA_BASELINE_MANIFEST_PATH:?Debian manifest path required}"
snap_manifest="${LDA_BASELINE_SNAP_MANIFEST_PATH:?Snap manifest path required}"
test -r "$metadata"
test -r "$manifest"
command -v jq >/dev/null

jq -e --arg release "$expected_release" \
      --arg codename "$expected_codename" \
      --arg arch "$expected_arch" \
      --arg edition "${LDA_BASELINE_EDITION:?edition required}" \
      --arg iso "${LDA_BASELINE_ISO_SHA256:?ISO SHA256 required}" \
      --arg build "${LDA_BASELINE_ISO_BUILD_ID:?ISO build ID required}" \
      --arg rootfs "${LDA_BASELINE_ROOTFS_DIGEST:?rootfs digest required}" \
      '.release == $release and .codename == $codename and .architecture == $arch and
       .edition == $edition and .iso_sha256 == $iso and
       .iso_build_id == $build and .rootfs_digest == $rootfs' \
      "$metadata" >/dev/null

actual_manifest_sha="$(sha256sum "$manifest" | awk '{print $1}')"
test "$actual_manifest_sha" = "${LDA_BASELINE_MANIFEST_SHA256:?manifest SHA256 required}"

inventory_sha="$(dpkg-query -W -f='${binary:Package}\t${Version}\t${Architecture}\n' | LC_ALL=C sort | sha256sum | awk '{print $1}')"
test "$inventory_sha" = "${LDA_BASELINE_PACKAGE_INVENTORY_DIGEST:?package inventory digest required}"

test -r "$snap_manifest"
actual_snap_sha="$(sha256sum "$snap_manifest" | awk '{print $1}')"
test "$actual_snap_sha" = "${LDA_BASELINE_SNAP_MANIFEST_SHA256:?Snap manifest SHA256 required}"
command -v snap >/dev/null
snap_inventory_sha="$(snap list --unicode=never | awk 'NR > 1 {print $1 \"\\t\" $3 \"\\t\" $4}' | LC_ALL=C sort | sha256sum | awk '{print $1}')"
test "$snap_inventory_sha" = "${LDA_BASELINE_SNAP_INVENTORY_DIGEST:?Snap inventory digest required}"

printf '%s\n' "iso_snapshot baseline verified: $metadata"
