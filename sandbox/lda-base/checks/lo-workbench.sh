#!/usr/bin/env bash
# libreoffice-core workbench helpers.
#
# The workload is headless document conversion, the path every `soffice
# --convert-to`, print-to-PDF and document-preview user takes: ODF flat-XML
# import (sax/xmloff), layout, and PDF export (vcl's PDF writer). Installed-
# state A/B: each mode's own .debs are installed with dpkg before measuring
# (outside the timed region), so soffice runs from its real installed paths.
set -euo pipefail
. /opt/lda/harness/checks/pkg-common.sh

LO_FIXDIR="${LDA_LO_FIXDIR:-/opt/lda/fixtures/libreoffice}"
LO_PROGRAM=/usr/lib/libreoffice/program/soffice.bin

lda_lo_env() {
  local mode="${1:?mode required}" root scratch list
  root="$(lda_pkg_root "$mode")"
  scratch="${LDA_REMOTE_TMPDIR:-/scratch/lda-hm}"
  list="/opt/lda/$mode/runtime-debs.list"
  test -s "$list" || { echo "no runtime deb list for $mode at $list" >&2; return 66; }
  test -x "$root/usr/lib/libreoffice/program/soffice.bin" || { echo "no soffice.bin under $root" >&2; return 66; }
  test -s "$LO_FIXDIR/params.env" || { echo "libreoffice fixtures missing; run prepare-lo-fixtures.sh first" >&2; return 66; }
  local debs=()
  mapfile -t debs <"$list"
  sudo -n dpkg -i "${debs[@]}" >"$scratch/lo-dpkg-$mode.log" 2>&1 || {
    tail -20 "$scratch/lo-dpkg-$mode.log" >&2; echo "could not install $mode libreoffice debs" >&2; return 70; }
  export LDA_LO_ROOT="$root" LDA_LO_SCRATCH="$scratch" LDA_LO_PROFILE="$scratch/lo-profile-$mode"
  export HOME="$scratch/lo-home-$mode" LC_ALL=C.UTF-8 TZ=UTC SAL_USE_VCLPLUGIN=svp \
    XDG_CACHE_HOME="$scratch/lo-cache-$mode" XDG_CONFIG_HOME="$scratch/lo-config-$mode" GSETTINGS_BACKEND=memory
  mkdir -p "$HOME" "$XDG_CACHE_HOME" "$XDG_CONFIG_HOME" "$LDA_LO_PROFILE"
  # shellcheck disable=SC1090
  . "$LO_FIXDIR/params.env"
}

lda_lo_attribution() {
  local mode="${1:?mode required}" f
  for f in usr/lib/libreoffice/program/soffice.bin usr/lib/libreoffice/program/libvcllo.so usr/lib/libreoffice/program/libxolo.so; do
    test -e "$LDA_LO_ROOT/$f" || continue
    test "$(sha256sum <"/$f")" = "$(sha256sum <"$LDA_LO_ROOT/$f")" || { echo "installed /$f is not the $mode build" >&2; return 65; }
  done
}

# Convert every fixture of one kind to PDF in a single soffice invocation and
# print the hash of the extracted text (PDF bytes carry timestamps).
lda_lo_convert() {
  local mode="$1" kind="$2" out
  out="$LDA_LO_SCRATCH/lo-out-$mode-$kind"
  rm -rf "$out"; mkdir -p "$out"
  "$LO_PROGRAM" "-env:UserInstallation=file://$LDA_LO_PROFILE" --headless --norestore --nologo --nolockcheck \
    --convert-to pdf --outdir "$out" "$LO_FIXDIR"/"$kind"-*.f* >/dev/null 2>"$out/stderr.log" || {
      tail -5 "$out/stderr.log" >&2; return 1; }
  for f in "$out"/*.pdf; do pdftotext -layout "$f" - 2>/dev/null; pdfinfo "$f" 2>/dev/null | grep '^Pages:'; done | sha256sum | cut -c1-16
  rm -rf "$out"
}
