#!/usr/bin/env bash
set -euo pipefail

sudo mkdir -p /opt/lda/build /opt/lda/candidate /opt/lda/output
sudo chown -R worker:worker /opt/lda/build /opt/lda/candidate /opt/lda/output /opt/lda/work
for path in /opt/lda/baseline /opt/lda/harness /opt/lda/fixtures; do
  sudo chown -R root:root "$path"
  sudo find "$path" -type d -exec chmod a-w {} +
  sudo find "$path" -type f -exec chmod a-w {} +
done
sudo rm -f /etc/sudoers.d/lda-worker
test -w /opt/lda/work
test -w /opt/lda/candidate
test ! -w /opt/lda/baseline
printf 'candidate workspace sealed\n'
