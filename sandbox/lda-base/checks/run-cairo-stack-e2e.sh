#!/usr/bin/env bash
# End-to-end benchmark for the cairo card: full-size PNG decode-to-surface
# over the e2e deck through the SELECTED libcairo2 (the GTK/librsvg asset
# path), pixels hashed for equivalence.
set -euo pipefail
mode="${1:-candidate}"
case "$mode" in baseline|candidate) ;; *) exit 64 ;; esac
. /opt/lda/harness/checks/cairo-workbench.sh
if test "$mode" = candidate; then
  /opt/lda/harness/checks/ensure-pkg-candidate.sh
fi
lda_cairo_prepare
lda_cairo_attribution "$mode"

fixroot="${LDA_CAIRO_FIXDIR:-/opt/lda/fixtures/libpng}"
deck=("$fixroot"/e2e-deck/deck-*.png)
test "${#deck[@]}" -ge 8 || { echo "e2e deck missing" >&2; exit 65; }
passes="${LDA_CAIRO_E2E_PASSES:-14}"

lda_run_with_pkg "$mode" "$CAIRO_FIXDIR/cairo-ops" png-load 1 "${deck[@]:0:4}" >/dev/null

lda_bench_run end_to_end cairo-png-load "$mode" $((passes * ${#deck[@]})) \
  lda_run_with_pkg "$mode" "$CAIRO_FIXDIR/cairo-ops" png-load "$passes" "${deck[@]}"

printf 'cairo stack e2e mode=%s passes=%s complete\n' "$mode" "$passes"
