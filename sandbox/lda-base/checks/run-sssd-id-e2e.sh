#!/usr/bin/env bash
# End-to-end benchmark for the sssd card: the real admin-tool shape - fresh
# processes resolving identities through NSS (fork + libnss_sss + daemon),
# the way id/getent/login paths actually hit sssd. Regression guardrail.
set -euo pipefail
mode="${1:-candidate}"
case "$mode" in baseline|candidate) ;; *) exit 64 ;; esac
. /opt/lda/harness/checks/sssd-workbench.sh
if test "$mode" = candidate; then
  /opt/lda/harness/checks/ensure-pkg-candidate.sh
fi
lda_sssd_install_mode "$mode"
lda_sssd_restart
fixdir="${LDA_SSSD_FIXDIR:-$SSSD_FIXDIR_DEFAULT}"
rounds=$(( ${LDA_SSSD_E2E_ROUNDS:-300} ))

e2e_loop() {
  local digest=""
  for i in $(seq 0 $((rounds - 1))); do
    digest="$digest$(getent passwd "lda_u$(( (i * 37) % 3000 ))" | cut -d: -f1,3,5)"
  done
  printf '%s' "$digest" | sha256sum | cut -c1-16
}

# Warmup.
getent passwd lda_u0 >/dev/null

lda_bench_run end_to_end getent-processes "$mode" "$rounds" e2e_loop
printf 'sssd id e2e mode=%s complete\n' "$mode"
