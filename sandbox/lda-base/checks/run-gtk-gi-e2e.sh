#!/usr/bin/env bash
# End-to-end benchmark for the gtk cards: the same widget-churn workload real
# GNOME applications run - through the gi binding stack - against the selected
# libgtk. Regression guardrail: most of its cycles are legitimately outside
# this package (binding, pango, glib), so the card sets no minimum here.
set -euo pipefail
mode="${1:-candidate}"
case "$mode" in baseline|candidate) ;; *) exit 64 ;; esac
. /opt/lda/harness/checks/gtk-workbench.sh
if test "$mode" = candidate; then
  /opt/lda/harness/checks/ensure-pkg-candidate.sh
fi
lda_gtk_prepare
lda_gtk_attribution "$mode"
major="$(lda_gtk_major)"

script=/opt/lda/harness/checks/gtk-gi-churn.py
test -s "$script" || { echo "GTK GI workload asset missing" >&2; exit 65; }

rounds=$(( ${LDA_GTK_E2E_ROUNDS:-40} ))
# Warmup (unmeasured).
lda_run_with_pkg "$mode" python3 "$script" "$major" 2 >/dev/null
lda_bench_run end_to_end gtk-gi-churn "$mode" "$rounds" \
  lda_run_with_pkg "$mode" python3 "$script" "$major" "$rounds"
printf 'gtk%s gi e2e mode=%s complete\n' "$major" "$mode"
