#!/usr/bin/env bash
# Baseline-tests fence for the generic workbench: the candidate rebuild ran
# the package's own upstream test suite (dh_auto_test inside
# dpkg-buildpackage) and the build log proves it. A packaging that visibly
# disables its own build-time tests is reported as not-applicable rather
# than silently assumed to have tested.
set -euo pipefail
/opt/lda/harness/checks/ensure-pkg-candidate.sh
state="$(cat /opt/lda/candidate/upstream-tests-state 2>/dev/null || echo missing)"
case "$state" in
  reference)
    reference=/opt/lda/baseline/upstream-tests-failures
    candidate=/opt/lda/candidate/upstream-tests-failures
    test -f "$reference" || { echo "baseline failure reference missing" >&2; exit 1; }
    test -f "$candidate" || { echo "candidate failure record missing" >&2; exit 1; }
    regressions="$(LC_ALL=C comm -13 "$reference" "$candidate")"
    if test -n "$regressions"; then
      echo "upstream suite regressions vs the baseline reference:" >&2
      printf '%s\n' "$regressions" >&2
      exit 1
    fi
    printf 'REFERENCE: candidate failure set within baseline (%s baseline failures, %s candidate)\n' \
      "$(wc -l <"$reference")" "$(wc -l <"$candidate")"
    ;;
  ran)
    printf 'candidate rebuild ran the upstream test suite (dh_auto_test evidenced in build log)\n'
    ;;
  packaging-disables-tests)
    printf 'NOT-APPLICABLE: debian/rules visibly disables dh_auto_test; no upstream suite runs at build time\n'
    ;;
  *)
    echo "upstream test evidence missing: state=$state" >&2
    exit 1
    ;;
esac
test -z "$(git -C /opt/lda/work status --porcelain)"
