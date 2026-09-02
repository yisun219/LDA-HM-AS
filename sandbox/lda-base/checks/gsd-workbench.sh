#!/usr/bin/env bash
# gnome-settings-daemon workbench helpers.
#
# What a login session pays for this package is the start of its plugin
# daemons (gsd-* under /usr/libexec): each loads its settings, connects to
# the session/system buses and claims org.gnome.SettingsDaemon.<Plugin>.
# The timed work is exactly that, inside private buses with python-dbusmock
# stand-ins for logind, UPower, NetworkManager, polkit, power-profiles-daemon
# and gnome-session. Installed-state A/B: each mode's own .debs are installed
# with dpkg before measuring (outside the timed region).
set -euo pipefail
. /opt/lda/harness/checks/pkg-common.sh

GSD_FIXDIR="${LDA_GSD_FIXDIR:-/opt/lda/fixtures/gsd}"
GSD_PLUGINS="${LDA_GSD_PLUGINS:-a11y-settings datetime housekeeping rfkill screensaver-proxy sharing sound power print-notifications usb-protection}"

lda_gsd_env() {
  local mode="${1:?mode required}" root scratch list
  root="$(lda_pkg_root "$mode")"
  scratch="${LDA_REMOTE_TMPDIR:-/scratch/lda-hm}"
  list="/opt/lda/$mode/runtime-debs.list"
  test -s "$list" || { echo "no runtime deb list for $mode at $list" >&2; return 66; }
  test -x "$root/usr/libexec/gsd-datetime" || { echo "no gsd plugins under $root/usr/libexec" >&2; return 66; }
  local debs=()
  mapfile -t debs <"$list"
  sudo -n dpkg -i "${debs[@]}" >"$scratch/gsd-dpkg-$mode.log" 2>&1 || {
    tail -20 "$scratch/gsd-dpkg-$mode.log" >&2; echo "could not install $mode gnome-settings-daemon debs" >&2; return 70; }
  export LDA_GSD_ROOT="$root" LDA_GSD_SCRATCH="$scratch"
  export XDG_RUNTIME_DIR="$scratch/gsd-xdg-$mode" XDG_CACHE_HOME="$scratch/gsd-cache-$mode" \
    XDG_CONFIG_HOME="$scratch/gsd-config-$mode" XDG_DATA_HOME="$scratch/gsd-data-$mode" \
    GSETTINGS_BACKEND=memory LC_ALL=C.UTF-8 TZ=UTC NO_AT_BRIDGE=1 GTK_A11Y=none
  mkdir -p "$XDG_RUNTIME_DIR" "$XDG_CACHE_HOME" "$XDG_CONFIG_HOME" "$XDG_DATA_HOME"; chmod 700 "$XDG_RUNTIME_DIR"
}

lda_gsd_attribution() {
  local mode="${1:?mode required}" f lib
  lib="$(ls -d "$LDA_GSD_ROOT"/usr/lib/gnome-settings-daemon-*/libgsd.so 2>/dev/null | head -1)"
  for f in usr/libexec/gsd-datetime usr/libexec/gsd-sharing "${lib#"$LDA_GSD_ROOT"/}"; do
    test "$(sha256sum <"/$f")" = "$(sha256sum <"$LDA_GSD_ROOT/$f")" || {
      echo "installed /$f is not the $mode build" >&2; return 65; }
  done
}

# Start every plugin, wait for its bus name, stop it. `parallel` starts them
# all at once the way gnome-session does; otherwise one after another.
# Prints the sorted list of claimed names (the hash source) as the last line.
lda_gsd_session() {
  local mode="$1" iterations="$2" parallel="$3"
  export _LDA_BENCH_NONCE
  python3 /opt/lda/harness/checks/lda-session-runner.py -- \
    python3 /opt/lda/harness/checks/gsd-session.py "$iterations" "$parallel" $GSD_PLUGINS
}
