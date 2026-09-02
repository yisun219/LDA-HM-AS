#!/usr/bin/env bash
# Runtime for the plugins-good workbench, from the pinned snapshot.
set -euo pipefail
apt_root=/opt/lda/apt
sources="$apt_root/snapshot.sources"
test -s "$sources" || { echo "snapshot sources missing" >&2; exit 78; }
OPTS=(-o "Dir::Etc::sourcelist=$sources" -o "Dir::Etc::sourceparts=-"
      -o "Dir::State::lists=$apt_root/lists" -o "Dir::Cache=$apt_root/cache"
      -o "APT::Get::List-Cleanup=0" -o "Acquire::Check-Valid-Until=false")
sudo -n apt-get "${OPTS[@]}" install -y --allow-downgrades --no-install-recommends \
  gstreamer1.0-tools gstreamer1.0-plugins-base gstreamer1.0-plugins-good
/opt/lda/harness/checks/prepare-gst-fixtures.sh
echo "gst workbench installed (tools, base, plugins-good runtime, fixtures)"
