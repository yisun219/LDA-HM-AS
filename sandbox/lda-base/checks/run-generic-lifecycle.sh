#!/usr/bin/env bash
# Generic package lifecycle fence: the candidate debs install over stock,
# the (card-provided) consumer probe still runs, and stock rolls back.
#   LDA_PKG_PROBE  command run after install and after rollback (default: ldconfig sanity)
set -euo pipefail
probe="${LDA_PKG_PROBE:-ldconfig -p >/dev/null}"

mapfile -t baseline_debs </opt/lda/baseline/runtime-debs.list
mapfile -t candidate_debs </opt/lda/candidate/runtime-debs.list
test "${#candidate_debs[@]}" -ge 1

rollback() {
  sudo -n dpkg -i "${baseline_debs[@]}" >/dev/null 2>&1 || true
}
trap rollback EXIT
sudo -n dpkg -i "${candidate_debs[@]}"
bash -c "$probe"
sudo -n dpkg -i "${baseline_debs[@]}"
bash -c "$probe"
trap - EXIT
for deb in "${baseline_debs[@]}"; do
  name="$(dpkg-deb -f "$deb" Package)"
  want="$(dpkg-deb -f "$deb" Version)"
  have="$(dpkg-query -W -f='${Version}' "$name")"
  test "$have" = "$want" || { echo "rollback left $name at $have (want $want)" >&2; exit 1; }
done
printf 'candidate install, probe, and rollback passed (%d debs)\n' "${#candidate_debs[@]}"
