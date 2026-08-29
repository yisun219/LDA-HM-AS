#!/usr/bin/env bash
# Install the gtk card's runtime consumers from the pinned snapshot: the gtk
# runtime itself plus the gi binding stack the end-to-end deck drives.
set -euo pipefail
major="${LDA_GTK_MAJOR:?LDA_GTK_MAJOR (3 or 4) is required}"
apt_root=/opt/lda/apt
sources="$apt_root/snapshot.sources"
test -s "$sources" || { echo "snapshot sources missing" >&2; exit 78; }
OPTS=(-o "Dir::Etc::sourcelist=$sources" -o "Dir::Etc::sourceparts=-"
      -o "Dir::State::lists=$apt_root/lists" -o "Dir::Cache=$apt_root/cache"
      -o "APT::Get::List-Cleanup=0" -o "Acquire::Check-Valid-Until=false")
case "$major" in
  4) packages=(libgtk-4-1 gir1.2-gtk-4.0) ;;
  3) packages=(libgtk-3-0t64 gir1.2-gtk-3.0) ;;
  *) exit 64 ;;
esac
sudo -n apt-get "${OPTS[@]}" install -y --allow-downgrades --no-install-recommends \
  "${packages[@]}" python3-gi fontconfig fonts-dejavu-core adwaita-icon-theme \
  shared-mime-info
echo "gtk$major workbench installed (runtime, gi bindings, fonts)"
