#!/usr/bin/env bash
# Dependency-tests fence: the package's own autopkgtest suite (debian/tests)
# runs on this testbed against the INSTALLED debs (null runner).
#   baseline mode (setup): record which tests pass with baseline debs.
#   candidate mode (fence): every test that passed on baseline must pass
#   again with the candidate debs installed; a new failure is a veto.
# Four-state: passed / failed / NOT-APPLICABLE (no debian/tests) / infra.
set -euo pipefail
mode="${1:?baseline or candidate required}"
case "$mode" in baseline|candidate) ;; *) exit 64 ;; esac
work=/opt/lda/work
summary_dir="/opt/lda/$mode"

if ! test -s "$work/debian/tests/control"; then
  printf 'NOT-APPLICABLE: source ships no autopkgtest (debian/tests/control absent)\n'
  exit 0
fi
if test "$mode" = candidate; then
  /opt/lda/harness/checks/ensure-pkg-candidate.sh
fi
command -v autopkgtest >/dev/null || {
  echo "autopkgtest is not installed (run install-test-tools.sh in setup)" >&2
  exit 69
}

mapfile -t debs <"$summary_dir/runtime-debs.list"
mapfile -t baseline_debs </opt/lda/baseline/runtime-debs.list
out="$(mktemp -d)"
rollback() { sudo -n dpkg -i "${baseline_debs[@]}" >/dev/null 2>&1 || true; }
trap rollback EXIT
sudo -n dpkg -i "${debs[@]}" >/dev/null

rc=0
sudo -n timeout 2700 autopkgtest -B "$work" \
  --output-dir "$out/run" --summary "$out/summary" -- null >"$out/log" 2>&1 || rc=$?
sudo -n chown -R "$(id -u):$(id -g)" "$out" 2>/dev/null || true

case "$rc" in
  0|2|4|12) ;;  # ran (all pass / skips / failures - judged below)
  8)
    printf 'NOT-APPLICABLE: autopkgtest declared no tests to run\n'
    exit 0
    ;;
  6|16|124)
    echo "autopkgtest testbed failure (infrastructure): rc=$rc" >&2
    tail -20 "$out/log" >&2
    exit 1
    ;;
  *)
    echo "autopkgtest errored: rc=$rc" >&2
    tail -40 "$out/log" >&2
    exit 1
    ;;
esac

test -s "$out/summary" || { echo "autopkgtest produced no summary" >&2; exit 1; }
awk '{print $1, $2}' "$out/summary" | LC_ALL=C sort >"$summary_dir/autopkgtest.summary"

if test "$mode" = candidate; then
  reference=/opt/lda/baseline/autopkgtest.summary
  test -s "$reference" || { echo "baseline autopkgtest summary missing" >&2; exit 1; }
  regressions="$(join "$reference" "$summary_dir/autopkgtest.summary" 2>/dev/null | \
    awk '$2 == "PASS" && $3 != "PASS" {print $1 ": baseline PASS -> candidate " $3}')"
  if test -n "$regressions"; then
    echo "autopkgtest regressions vs baseline:" >&2
    printf '%s\n' "$regressions" >&2
    tail -40 "$out/log" >&2
    exit 1
  fi
fi

passes="$(awk '$2 == "PASS"' "$summary_dir/autopkgtest.summary" | wc -l)"
total="$(wc -l <"$summary_dir/autopkgtest.summary")"
printf 'autopkgtest %s: %s/%s tests passing recorded\n' "$mode" "$passes" "$total"
