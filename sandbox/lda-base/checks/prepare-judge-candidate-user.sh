#!/usr/bin/env bash
set -euo pipefail

id judge-builder >/dev/null 2>&1 || sudo useradd --create-home --shell /bin/bash judge-builder
sudo mkdir -p /opt/lda/build /opt/lda/candidate /opt/lda/output
sudo chown -R judge-builder:judge-builder /opt/lda/work /opt/lda/build /opt/lda/candidate /opt/lda/output
for path in /opt/lda/baseline /opt/lda/harness /opt/lda/fixtures /opt/lda/input; do
  sudo chown -R root:root "$path"
  sudo find "$path" -type d -exec chmod a-w {} +
  sudo find "$path" -type f -exec chmod a-w {} +
done
sudo find /opt/lda/input -type d -exec chmod a+rx {} +
sudo find /opt/lda/input -type f -exec chmod a+r {} +
test "$(sudo -u judge-builder sh -lc 'id -u')" = "$(id -u judge-builder)"
if sudo -u judge-builder sudo -n true 2>/dev/null; then
  echo "judge-builder unexpectedly has sudo" >&2
  exit 77
fi
printf 'judge candidate user prepared\n'
