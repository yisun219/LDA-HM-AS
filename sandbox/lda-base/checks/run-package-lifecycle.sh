#!/usr/bin/env bash
set -euo pipefail
. /opt/lda/harness/checks/libpng-common.sh
/opt/lda/harness/checks/ensure-libpng-candidate.sh
baseline_deb="$(cat /opt/lda/baseline/runtime-deb.path)"
candidate_deb="$(cat /opt/lda/candidate/runtime-deb.path)"
test "$(dpkg-deb -f "$candidate_deb" Package)" = libpng16-16t64
test "$(dpkg-deb -f "$candidate_deb" Version)" = 1.6.57-1
test "$(dpkg-deb -f "$candidate_deb" Architecture)" = amd64
trap 'sudo -n dpkg -i "$baseline_deb" >/dev/null 2>&1 || true' EXIT
sudo -n dpkg -i "$candidate_deb"
/opt/lda/fixtures/libpng/libpng-consumer /opt/lda/fixtures/libpng/small.png 1 >/dev/null
sudo -n dpkg -i "$baseline_deb"
test "$(dpkg-query -W -f='${Version}' libpng16-16t64)" = 1.6.57-1
trap - EXIT
printf '%s\n' "candidate install, existing-binary execution, and rollback passed"
