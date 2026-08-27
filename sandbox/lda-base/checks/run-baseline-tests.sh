#!/usr/bin/env bash
set -euo pipefail
/opt/lda/harness/checks/ensure-libpng-candidate.sh
test -f /opt/lda/candidate/upstream-tests-passed
test -z "$(git -C /opt/lda/work status --porcelain)"
printf '%s\n' "candidate Debian build and upstream libpng tests passed"
