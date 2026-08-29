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

script=/opt/lda/fixtures/gtk-bench/gi-churn.py
if ! test -s "$script"; then
  cat >"$script" <<'PYW'
import hashlib
import sys

major, rounds = sys.argv[1], int(sys.argv[2])
import gi

gi.require_version("Gtk", "4.0" if major == "4" else "3.0")
from gi.repository import Gtk

digest = hashlib.sha256()
window = Gtk.Window()
for round_number in range(rounds):
    grid = Gtk.Grid()
    for index in range(300):
        label = Gtk.Label(label=f"item {round_number}-{index}")
        if major == "4":
            label.add_css_class("title-2" if index % 3 else "dim-label")
        else:
            label.get_style_context().add_class(
                "title-2" if index % 3 else "dim-label"
            )
        grid.attach(label, index % 20, index // 20, 1, 1)
    if major == "4":
        window.set_child(grid)
        minimum, natural, _b1, _b2 = grid.measure(Gtk.Orientation.HORIZONTAL, -1)
    else:
        window.add(grid)
        grid.show_all()
        minimum, natural = grid.get_preferred_width()
        window.remove(grid)
    digest.update(f"{minimum}:{natural}".encode())
print(digest.hexdigest()[:16])
PYW
fi

rounds=$(( ${LDA_GTK_E2E_ROUNDS:-40} ))
# Warmup (unmeasured).
lda_run_with_pkg "$mode" python3 "$script" "$major" 2 >/dev/null
lda_bench_run end_to_end gtk-gi-churn "$mode" "$rounds" \
  lda_run_with_pkg "$mode" python3 "$script" "$major" "$rounds"
printf 'gtk%s gi e2e mode=%s complete\n' "$major" "$mode"
