#!/usr/bin/env bash
# Instrument falsification before any candidate is judged: every timed
# element must resolve to the mode's own build, and the probe must be
# deterministic across two runs of the same mode.
set -euo pipefail
. /opt/lda/harness/checks/gst-workbench.sh
# The candidate build at round 0 is the baseline source rebuilt: an A-A pair
# for falsifying the instrument before any patch exists.
/opt/lda/harness/checks/ensure-pkg-candidate.sh
for mode in baseline candidate; do
  lda_gst_env "$mode"; lda_gst_attribution "$mode"
  a="$(/opt/lda/harness/checks/run-gst-good-probe.sh "$mode")"
  b="$(/opt/lda/harness/checks/run-gst-good-probe.sh "$mode")"
  test "$a" = "$b" || { echo "gst-good probe is not deterministic in $mode: $a vs $b" >&2; exit 1; }
done
echo "gst-good selfcheck passed"
