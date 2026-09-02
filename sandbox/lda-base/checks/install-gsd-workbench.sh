#!/usr/bin/env bash
set -euo pipefail
apt_root=/opt/lda/apt
sources="$apt_root/snapshot.sources"
test -s "$sources" || { echo "snapshot sources missing" >&2; exit 78; }
OPTS=(-o "Dir::Etc::sourcelist=$sources" -o "Dir::Etc::sourceparts=-"
      -o "Dir::State::lists=$apt_root/lists" -o "Dir::Cache=$apt_root/cache"
      -o "APT::Get::List-Cleanup=0" -o "Acquire::Check-Valid-Until=false")
sudo -n apt-get "${OPTS[@]}" install -y --allow-downgrades --no-install-recommends \
  gnome-settings-daemon gnome-settings-daemon-common python3-dbusmock python3-dbus python3-gi \
  gsettings-desktop-schemas dconf-gsettings-backend dbus-daemon
mkdir -p /opt/lda/fixtures/gsd
echo "gsd workbench installed (runtime, mock session runner)"
