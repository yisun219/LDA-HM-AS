#!/usr/bin/env bash
# Install only the runtime consumers needed by the executable top-10 cards and
# create deterministic fixtures before /opt/lda/fixtures is sealed.
set -euo pipefail
pkg="${LDA_TOP10_PACKAGE:?LDA_TOP10_PACKAGE required}"
apt_root=/opt/lda/apt
sources="$apt_root/snapshot.sources"
test -s "$sources" || { echo "snapshot sources missing" >&2; exit 78; }
OPTS=(-o "Dir::Etc::sourcelist=$sources" -o "Dir::Etc::sourceparts=-"
      -o "Dir::State::lists=$apt_root/lists" -o "Dir::Cache=$apt_root/cache"
      -o "APT::Get::List-Cleanup=0" -o "Acquire::Check-Valid-Until=false")

case "$pkg" in
  gnome-shell) packages=(gnome-shell gjs dbus-x11 xvfb) ;;
  libreoffice-core) packages=(libreoffice-core libreoffice-common poppler-utils) ;;
  gnome-settings-daemon) packages=(gnome-settings-daemon dbus-x11) ;;
  gstreamer1.0-plugins-good) packages=(gstreamer1.0-tools gstreamer1.0-plugins-base gstreamer1.0-plugins-good) ;;
  ibus) packages=(ibus dbus-x11 xvfb) ;;
  *) echo "unsupported top10 workbench package: $pkg" >&2; exit 64 ;;
esac
sudo -n apt-get "${OPTS[@]}" install -y --allow-downgrades --no-install-recommends "${packages[@]}"

fixdir=/opt/lda/fixtures/top10
mkdir -p "$fixdir"
case "$pkg" in
  libreoffice-core)
    cat >"$fixdir/sample.fodt" <<'FODT'
<?xml version="1.0" encoding="UTF-8"?>
<office:document xmlns:office="urn:oasis:names:tc:opendocument:xmlns:office:1.0" xmlns:text="urn:oasis:names:tc:opendocument:xmlns:text:1.0" office:mimetype="application/vnd.oasis.opendocument.text">
 <office:body><office:text><text:h text:outline-level="1">LDA Ubuntu 26.04 benchmark</text:h>
  <text:p>Deterministic document conversion fixture for surgical replacement validation.</text:p>
  <text:p>$(printf 'repeat %.0s' {1..80})</text:p>
 </office:text></office:body>
</office:document>
FODT
    ;;
  gstreamer1.0-plugins-good)
    gst-launch-1.0 -q audiotestsrc num-buffers=900 wave=sine ! audio/x-raw,rate=44100,channels=2 ! wavenc ! filesink location="$fixdir/sample.wav"
    gst-launch-1.0 -q filesrc location="$fixdir/sample.wav" ! wavparse ! flacenc ! filesink location="$fixdir/sample.flac"
    ;;
esac
printf 'top10 workbench installed for %s\n' "$pkg"
