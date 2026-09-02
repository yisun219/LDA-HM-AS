#!/usr/bin/env bash
set -euo pipefail
apt_root=/opt/lda/apt
sources="$apt_root/snapshot.sources"
test -s "$sources" || { echo "snapshot sources missing" >&2; exit 78; }
OPTS=(-o "Dir::Etc::sourcelist=$sources" -o "Dir::Etc::sourceparts=-"
      -o "Dir::State::lists=$apt_root/lists" -o "Dir::Cache=$apt_root/cache"
      -o "APT::Get::List-Cleanup=0" -o "Acquire::Check-Valid-Until=false")
sudo -n apt-get "${OPTS[@]}" install -y --allow-downgrades --no-install-recommends \
  ibus libibus-1.0-5 gir1.2-ibus-1.0 python3-gi dbus-daemon dbus-x11 dconf-gsettings-backend gsettings-desktop-schemas
/opt/lda/harness/checks/prepare-ibus-fixtures.sh
echo "ibus workbench installed (runtime, gi bindings, session bus, fixtures)"
