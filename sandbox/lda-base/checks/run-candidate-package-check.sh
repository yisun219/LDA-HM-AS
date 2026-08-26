#!/usr/bin/env bash
set -euo pipefail

action="${1:?action required}"
shift
apt_root=/opt/lda/apt
sources="$apt_root/snapshot.sources"
apt_options=(
  -o "Dir::Etc::sourcelist=$sources"
  -o "Dir::Etc::sourceparts=-"
  -o "Dir::State::lists=$apt_root/lists"
  -o "Dir::Cache=$apt_root/cache"
  -o "APT::Get::List-Cleanup=0"
  -o "Acquire::Check-Valid-Until=false"
)

install_candidate() {
  mapfile -t candidate_debs </opt/lda/candidate/runtime-debs.list
  test "${#candidate_debs[@]}" -gt 0
  if ! sudo dpkg -i "${candidate_debs[@]}"; then
    sudo apt-get "${apt_options[@]}" -f install -y --allow-downgrades
    sudo dpkg -i "${candidate_debs[@]}"
  fi
  sudo ldconfig
  dpkg --audit
  while IFS= read -r candidate; do
    relative="${candidate#/opt/lda/candidate/root}"
    test -f "$relative"
    test "$(sha256sum "$candidate" | cut -d' ' -f1)" = "$(sha256sum "$relative" | cut -d' ' -f1)"
  done </opt/lda/candidate/libraries.list
  touch /opt/lda/candidate/packages-installed
}

case "$action" in
  install)
    install_candidate
    ;;
  reverse-build-test)
    package="${1:?reverse dependency package required}"
    test -f /opt/lda/candidate/packages-installed || install_candidate
    case "$package" in *[!a-zA-Z0-9+.:~-]*) exit 64 ;; esac
    root="$(mktemp -d)"
    trap 'rm -rf "$root"' EXIT
    source_package="$(apt-cache "${apt_options[@]}" show "$package" | sed -n 's/^Source: \([^ (]*\).*/\1/p' | head -1)"
    source_package="${source_package:-$package}"
    printf 'reverse binary=%s source=%s\n' "$package" "$source_package"
    sudo apt-get "${apt_options[@]}" build-dep -y --allow-downgrades "$source_package"
    cd "$root"
    DEB_BUILD_OPTIONS="parallel=$(nproc)" apt-get "${apt_options[@]}" source --compile "$source_package"
    sudo apt-get "${apt_options[@]}" install -y --allow-downgrades "$package"
    dpkg --verify "$package"
    while IFS= read -r executable; do
      file "$executable" | grep -q ELF || continue
      ldd "$executable" 2>/dev/null | tee "$root/ldd.txt"
      ! grep -q 'not found' "$root/ldd.txt"
    done < <(dpkg -L "$package" | while read -r path; do test -f "$path" -a -x "$path" && printf '%s\n' "$path"; done)
    ;;
  application-smoke)
    test -f /opt/lda/candidate/packages-installed || install_candidate
    /opt/lda/fixtures/generic/probe 1000 >/opt/lda/candidate/application-smoke.out
    while IFS= read -r deb; do
      package="$(dpkg-deb -f "$deb" Package)"
      dpkg-query -W -f='${db:Status-Status}\n' "$package" | grep -qx installed
      dpkg --verify "$package"
    done </opt/lda/candidate/runtime-debs.list
    ;;
  *) exit 64 ;;
esac

printf 'PASS %s\n' "$action"
