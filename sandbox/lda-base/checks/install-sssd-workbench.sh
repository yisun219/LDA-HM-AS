#!/usr/bin/env bash
# Install the sssd card's runtime consumers from the pinned snapshot, seed
# the synthetic identity universe, and configure the headless proxy-files
# domain the benchmarks exercise. Run once at setup, after the fixtures.
set -euo pipefail
apt_root=/opt/lda/apt
sources="$apt_root/snapshot.sources"
test -s "$sources" || { echo "snapshot sources missing" >&2; exit 78; }
OPTS=(-o "Dir::Etc::sourcelist=$sources" -o "Dir::Etc::sourceparts=-"
      -o "Dir::State::lists=$apt_root/lists" -o "Dir::Cache=$apt_root/cache"
      -o "APT::Get::List-Cleanup=0" -o "Acquire::Check-Valid-Until=false")
sudo -n apt-get "${OPTS[@]}" install -y --allow-downgrades --no-install-recommends \
  sssd-common libnss-sss sssd-proxy linux-perf 2>/dev/null || \
sudo -n apt-get "${OPTS[@]}" install -y --allow-downgrades --no-install-recommends \
  sssd-common libnss-sss sssd-proxy

fixdir=/opt/lda/fixtures/sssd
test -s "$fixdir/users.txt" || { echo "run prepare-sssd-fixtures.sh first" >&2; exit 66; }
if ! grep -q '^lda_u0:' /etc/passwd; then
  sudo -n sh -c "cat $fixdir/users.txt >> /etc/passwd"
fi
grep -c '^lda_u' /etc/passwd

sudo -n tee /etc/sssd/sssd.conf >/dev/null <<'EOF'
[sssd]
services = nss
domains = ldafiles

[nss]

[domain/ldafiles]
id_provider = proxy
proxy_lib_name = files
proxy_pam_target = login
enumerate = false
EOF
sudo -n chmod 600 /etc/sssd/sssd.conf
sudo -n sed -i 's/^passwd:.*/passwd:         sss files/; s/^group:.*/group:          sss files/' /etc/nsswitch.conf

. /opt/lda/harness/checks/sssd-workbench.sh
lda_sssd_restart
echo "sssd workbench installed and the stock daemon answers"
