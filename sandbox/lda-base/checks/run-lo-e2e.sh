#!/usr/bin/env bash
# End to end: the same documents through the other office formats a user
# exchanges (DOCX and XLSX export, then re-import of the exported files).
set -euo pipefail
mode="${1:-candidate}"; case "$mode" in baseline|candidate) ;; *) exit 64 ;; esac
. /opt/lda/harness/checks/lo-workbench.sh
lda_lo_env "$mode"
lda_lo_attribution "$mode"
roundtrip() {
  local out="$LDA_LO_SCRATCH/lo-rt-$mode"
  rm -rf "$out"; mkdir -p "$out"
  "$LO_PROGRAM" "-env:UserInstallation=file://$LDA_LO_PROFILE" --headless --norestore --nologo --nolockcheck \
    --convert-to docx --outdir "$out" "$LO_FIXDIR"/writer-*.fodt >/dev/null 2>&1
  "$LO_PROGRAM" "-env:UserInstallation=file://$LDA_LO_PROFILE" --headless --norestore --nologo --nolockcheck \
    --convert-to xlsx --outdir "$out" "$LO_FIXDIR"/calc-*.fods >/dev/null 2>&1
  "$LO_PROGRAM" "-env:UserInstallation=file://$LDA_LO_PROFILE" --headless --norestore --nologo --nolockcheck \
    --convert-to txt:Text --outdir "$out" "$out"/*.docx >/dev/null 2>&1
  "$LO_PROGRAM" "-env:UserInstallation=file://$LDA_LO_PROFILE" --headless --norestore --nologo --nolockcheck \
    --convert-to csv --outdir "$out" "$out"/*.xlsx >/dev/null 2>&1
  cat "$out"/*.txt "$out"/*.csv | sha256sum | cut -c1-16
  rm -rf "$out"
}
roundtrip >/dev/null
lda_bench_run end_to_end office-roundtrip "$mode" 1 roundtrip
printf 'libreoffice e2e mode=%s complete\n' "$mode"
