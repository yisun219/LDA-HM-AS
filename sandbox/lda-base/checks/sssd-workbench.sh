#!/usr/bin/env bash
# sssd workbench: installed-mode A/B. The sssd monitor execs absolute
# /usr/libexec/sssd paths, so the selected mode's runtime debs are INSTALLED
# per repetition (dpkg -i), the daemon restarted headless with caches reset,
# and only the lookup loop is timed. Both modes pay the identical switch
# cost outside the timed region.
set -euo pipefail
. /opt/lda/harness/checks/pkg-common.sh

SSSD_FIXDIR_DEFAULT=/opt/lda/fixtures/sssd

lda_sssd_install_mode() {
  local mode="${1:?baseline or candidate required}"
  case "$mode" in baseline|candidate) ;; *) return 64 ;; esac
  local marker=/opt/lda/.sssd-installed-mode
  if test -f "$marker" && test "$(cat "$marker")" = "$mode"; then
    return 0
  fi
  local listing="/opt/lda/$mode/runtime-debs.list"
  test -s "$listing" || { echo "runtime deb list missing for $mode" >&2; return 66; }
  # shellcheck disable=SC2046
  sudo -n dpkg -i --force-confold $(cat "$listing") >/dev/null
  printf '%s\n' "$mode" >"$marker"
}

lda_sssd_restart() {
  sudo -n pkill -x sssd 2>/dev/null || true
  sudo -n pkill -f sssd_be 2>/dev/null || true
  sudo -n pkill -f sssd_nss 2>/dev/null || true
  sleep 0.5
  sudo -n sh -c 'rm -rf /var/lib/sss/db/* /var/lib/sss/mc/* /var/log/sssd/*'
  sudo -n mkdir -p /var/lib/sss/db /var/lib/sss/mc /var/lib/sss/pipes/private
  (sudo -n /usr/sbin/sssd -i --logger=stderr >>/tmp/lda-sssd.log 2>&1 &)
  for _ in $(seq 1 80); do
    test -S /var/lib/sss/pipes/nss && break
    sleep 0.25
  done
  test -S /var/lib/sss/pipes/nss || {
    echo "sssd nss socket did not appear" >&2
    tail -12 /tmp/lda-sssd.log >&2 || true
    return 70
  }
  getent passwd lda_u0 >/dev/null || { echo "warm lookup failed" >&2; return 70; }
}

lda_sssd_lookup_tool() {
  local tool=/opt/lda/fixtures/sssd/lookup-runner.py
  test -s "$tool" && { printf '%s\n' "$tool"; return 0; }
  cat >"$tool" <<'PY'
import hashlib
import pwd
import sys

schedule_path, limit = sys.argv[1], int(sys.argv[2])
digest = hashlib.sha256()
count = 0
with open(schedule_path, encoding="utf-8") as stream:
    for line in stream:
        if count >= limit:
            break
        name = line.strip()
        if not name:
            continue
        try:
            entry = pwd.getpwnam(name)
            digest.update(f"{entry.pw_name}:{entry.pw_uid}:{entry.pw_gecos}".encode())
        except KeyError:
            digest.update(b"miss:" + name.encode())
        count += 1
print(digest.hexdigest()[:16])
PY
  printf '%s\n' "$tool"
}
