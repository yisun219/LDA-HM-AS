#!/usr/bin/env bash
# gnome-shell workbench helpers.
#
# The workload is the shell's own startup: gnome-shell started headless
# (mutter's headless backend, a virtual monitor, no X11) with an automation
# script, exactly the way GNOME's own shell tests and perf tool run it. The
# session services a shell expects (logind, gnome-session, UPower, Network
# Manager, polkit, AccountsService ...) are python-dbusmock stand-ins from
# gnome-shell's own test runner, on private session and system buses.
# What is timed is everything the package owns on the way to a usable
# shell: libst/libshell initialisation, theme and CSS loading, the JS UI
# bring-up in gjs, panel and overview construction, then orderly shutdown.
set -euo pipefail
. /opt/lda/harness/checks/pkg-common.sh

GS_FIXDIR="${LDA_GS_FIXDIR:-/opt/lda/fixtures/gnome-shell}"

# Installed-state A/B. gnome-shell's typelibs name their shared library by
# absolute path, so a copy pointed at through LD_LIBRARY_PATH is loaded a
# second time and GType registration collides. Instead each mode's own .deb
# is installed with dpkg before its measurement (outside the timed region),
# exactly how a user would replace the package, and the shell runs from its
# real installed paths.
lda_gs_env() {
  local mode="${1:?mode required}" root scratch list
  root="$(lda_pkg_root "$mode")"
  scratch="${LDA_REMOTE_TMPDIR:-/scratch/lda-hm}"
  list="/opt/lda/$mode/runtime-debs.list"
  test -s "$list" || { echo "no runtime deb list for $mode at $list" >&2; return 66; }
  test -e "$root/usr/lib/gnome-shell/libshell-18.so" || {
    echo "no libshell-18.so under $root/usr/lib/gnome-shell" >&2; return 66; }
  test -s "$GS_FIXDIR/startup.js" && test -s "$GS_FIXDIR/runner.py" || {
    echo "gnome-shell fixtures missing; run prepare-gnome-shell-fixtures.sh first" >&2; return 66; }
  local debs=()
  mapfile -t debs <"$list"
  sudo -n dpkg -i "${debs[@]}" >"$scratch/gs-dpkg-$mode.log" 2>&1 || {
    tail -20 "$scratch/gs-dpkg-$mode.log" >&2; echo "could not install $mode gnome-shell debs" >&2; return 70; }
  export LDA_GS_ROOT="$root" LDA_GS_SCRATCH="$scratch"
  export XDG_RUNTIME_DIR="$scratch/gs-xdg-$mode" XDG_CACHE_HOME="$scratch/gs-cache-$mode" \
    XDG_CONFIG_HOME="$scratch/gs-config-$mode" GSETTINGS_BACKEND=memory \
    GNOME_SHELL_SESSION_MODE=user LC_ALL=C.UTF-8 TZ=UTC \
    SHELL_BACKGROUND_IMAGE="$GS_FIXDIR/background.png" NO_AT_BRIDGE=1 GTK_A11Y=none
  unset GNOME_SHELL_DATADIR GI_TYPELIB_PATH LD_LIBRARY_PATH G_MESSAGES_DEBUG
  mkdir -p "$XDG_RUNTIME_DIR" "$XDG_CACHE_HOME" "$XDG_CONFIG_HOME"; chmod 700 "$XDG_RUNTIME_DIR"
}

# The installed shell must be byte-identical to this mode's build output.
lda_gs_attribution() {
  local mode="${1:?mode required}" f
  for f in usr/bin/gnome-shell usr/lib/gnome-shell/libshell-18.so usr/lib/gnome-shell/libst-18.so; do
    test "$(sha256sum <"/$f")" = "$(sha256sum <"$LDA_GS_ROOT/$f")" || {
      echo "installed /$f is not the $mode build" >&2; return 65; }
  done
}

# Run the automation script N times inside one mock-session runner and print
# the hash of the shell's own report lines (LDA-SHELL ...) as the last line.
# Timing is taken inside the runner, after the mocks are up, so the D-Bus
# stand-ins never count against the shell.
lda_gs_iterations() {
  local mode="$1" script="$2" iterations="$3" layer="$4" input="$5" log
  log="$LDA_GS_SCRATCH/gs-$mode-$input.log"
  export _LDA_BENCH_NONCE
  python3 "$GS_FIXDIR/runner.py" -- bash -c '
    . /opt/lda/harness/checks/pkg-common.sh
    shell_runs() {
      "$1" --headless --test-iters "$2" "$3" >"$4" 2>&1 || { echo "gnome-shell test tool failed (rc=$?)" >&2; tail -30 "$4" >&2; return 1; }
      grep -a "^LDA-SHELL " "$4" | sha256sum | cut -c1-16
    }
    lda_bench_run "$5" "$6" "$7" "$2" shell_runs "$1" "$2" "$3" "$4"
  ' _ /usr/bin/gnome-shell-test-tool "$iterations" "$GS_FIXDIR/$script" "$log" "$layer" "$input" "$mode"
}

lda_gs_probe_hash() {
  local mode="$1" log
  log="$LDA_GS_SCRATCH/gs-$mode-probe.log"
  python3 "$GS_FIXDIR/runner.py" -- /usr/bin/gnome-shell-test-tool --headless --test-iters 1 "$GS_FIXDIR/startup.js" >"$log" 2>&1 || {
    tail -20 "$log" >&2; return 1; }
  grep -a "^LDA-SHELL " "$log" | sha256sum | cut -c1-16
}
