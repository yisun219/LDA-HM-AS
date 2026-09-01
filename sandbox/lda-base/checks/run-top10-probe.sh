#!/usr/bin/env bash
set -euo pipefail
mode="${1:-candidate}"
case "$mode" in baseline|candidate) ;; *) exit 64 ;; esac
. /opt/lda/harness/checks/top10-workbench.sh
lda_top10_prepare
pkg="$LDA_TOP10_PACKAGE"
scratch="${LDA_REMOTE_TMPDIR:-/scratch/lda-hm}"
case "$pkg" in
  gnome-shell)
    program="$(lda_top10_program "$mode" usr/bin/gnome-shell /usr/bin/gnome-shell)"
    test -x "$program" || { echo "gnome-shell probe binary missing" >&2; exit 66; }
    lda_run_with_pkg "$mode" "$program" --version 2>&1 | sha256sum | cut -c1-16
    ;;
  libreoffice-core)
    program="$(lda_top10_program "$mode" usr/lib/libreoffice/program/soffice.bin /usr/lib/libreoffice/program/soffice.bin)"
    test -x "$program" || { echo "LibreOffice probe binary missing" >&2; exit 66; }
    out="$scratch/lo-probe-$mode"
    rm -rf "$out"; mkdir -p "$out"
    lda_run_with_pkg "$mode" "$program" --headless --convert-to pdf --outdir "$out" "$TOP10_FIXDIR/sample.fodt" >/dev/null
    pdftotext "$out/sample.pdf" - | sha256sum | cut -c1-16
    rm -rf "$out"
    ;;
  gnome-settings-daemon)
    program="$(find "$(lda_pkg_root "$mode")/usr/libexec" -maxdepth 1 -type f -name 'gsd-*' -perm -0100 2>/dev/null | LC_ALL=C sort | head -1)"
    test -n "$program" || program="$(find /usr/libexec -maxdepth 1 -type f -name 'gsd-*' -perm -0100 2>/dev/null | LC_ALL=C sort | head -1)"
    test -n "$program" || { echo "GSD probe binary missing" >&2; exit 66; }
    (lda_run_with_pkg "$mode" timeout 12 "$program" --version 2>&1 || true) | sha256sum | cut -c1-16
    ;;
  gstreamer1.0-plugins-good)
    lda_top10_gst_env "$mode"
    lda_run_with_pkg "$mode" gst-launch-1.0 -q filesrc location="$TOP10_FIXDIR/sample.wav" ! wavparse ! fakesink sync=false >/dev/null
    sha256sum "$TOP10_FIXDIR/sample.wav" | cut -c1-16
    ;;
  ibus)
    program="$(lda_top10_program "$mode" usr/bin/ibus-daemon /usr/bin/ibus-daemon)"
    dbus-run-session -- env LD_LIBRARY_PATH="$(lda_pkg_libdir "$mode")${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}" \
      "$program" --version 2>&1 | sha256sum | cut -c1-16
    ;;
  *) echo "unsupported top10 probe package: $pkg" >&2; exit 64 ;;
esac
