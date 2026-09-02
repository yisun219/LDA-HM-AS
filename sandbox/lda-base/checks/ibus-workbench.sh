#!/usr/bin/env bash
# ibus workbench helpers. The timed work is ibus's own code: the registry
# (component XML parsing, engine descriptions, cache serialisation) in
# libibus and the `ibus` tool, and the daemon/engine round trip that every
# keystroke on a desktop takes. GLib and D-Bus are the platform every
# consumer pays for; they are not what a candidate is allowed to "speed up".
set -euo pipefail
. /opt/lda/harness/checks/pkg-common.sh

IBUS_FIXDIR="${LDA_IBUS_FIXDIR:-/opt/lda/fixtures/ibus}"

lda_ibus_env() {
  local mode="${1:?mode required}" root scratch
  root="$(lda_pkg_root "$mode")"
  scratch="${LDA_REMOTE_TMPDIR:-/scratch/lda-hm}"
  test -x "$root/usr/bin/ibus" && test -x "$root/usr/bin/ibus-daemon" || {
    echo "no ibus build extracted under $root" >&2; return 66; }
  test -e "$root/usr/lib/x86_64-linux-gnu/libibus-1.0.so.5" || {
    echo "no libibus-1.0.so.5 under $root (card runtime debs must include libibus-1.0-5)" >&2; return 66; }
  test -s "$IBUS_FIXDIR/params.env" || {
    echo "ibus fixtures missing; run prepare-ibus-fixtures.sh first" >&2; return 66; }
  # shellcheck disable=SC1090
  . "$IBUS_FIXDIR/params.env"
  export LDA_IBUS_ROOT="$root" LDA_IBUS_SCRATCH="$scratch"
  export XDG_CACHE_HOME="$scratch/ibus-cache-$mode" XDG_CONFIG_HOME="$scratch/ibus-config-$mode" \
    XDG_RUNTIME_DIR="$scratch/ibus-xdg-$mode" GSETTINGS_BACKEND=memory LC_ALL=C.UTF-8 \
    IBUS_COMPONENT_PATH="$IBUS_FIXDIR/components"
  mkdir -p "$XDG_CACHE_HOME" "$XDG_CONFIG_HOME" "$XDG_RUNTIME_DIR"; chmod 700 "$XDG_RUNTIME_DIR"
  # The daemon spawns engines by the absolute path in the component file;
  # the session component set points at this mode's engine binary.
  # Component descriptions ship in the arch-independent ibus-data package,
  # so the system copies are the same for both modes; every executable they
  # name that this mode's build provides (engine, config module, ...) is
  # redirected to the mode's binary.
  local comp="$scratch/ibus-session-$mode" compdir f name
  compdir="$root/usr/share/ibus/component"
  test -d "$compdir" || compdir=/usr/share/ibus/component
  test -x "$root/usr/libexec/ibus-engine-simple" || { echo "no ibus-engine-simple under $root" >&2; return 66; }
  rm -rf "$comp"; mkdir -p "$comp"
  for f in "$compdir"/*.xml; do
    name="$(basename "$f")"
    sed -E "s#<exec>/usr/(libexec|bin)/(ibus-[a-z0-9-]+)#<exec>$root/usr/\\1/\\2#" "$f" >"$comp/$name"
    grep -o "<exec>[^ <]*" "$comp/$name" | sed 's#<exec>##' | while read -r exe; do
      test -x "$exe" || sed -i "s#<exec>$exe#<exec>${exe/$root/}#" "$comp/$name"
    done
  done
  export LDA_IBUS_SESSION_COMPONENTS="$comp"
}

lda_ibus_attribution() {
  local mode="${1:?mode required}" probe
  probe="$(mktemp)"
  LD_DEBUG=libs lda_run_with_pkg "$mode" "$LDA_IBUS_ROOT/usr/bin/ibus" version >/dev/null 2>"$probe" || true
  grep -F "$(lda_pkg_libdir "$mode")/libibus-1.0.so.5" "$probe" >/dev/null || {
    rm -f "$probe"; echo "ibus tool did not load $(lda_pkg_libdir "$mode")/libibus-1.0.so.5" >&2; return 65; }
  rm -f "$probe"
}

# Registry build from the component corpus, then a cache read-back; the
# hash covers the read-back text (engine order, names, ranks, layouts).
lda_ibus_registry() {
  local mode="$1" rounds="$2" i
  for i in $(seq 1 "$rounds"); do
    rm -rf "$XDG_CACHE_HOME/ibus"
    lda_run_with_pkg "$mode" "$LDA_IBUS_ROOT/usr/bin/ibus" write-cache >/dev/null
    lda_run_with_pkg "$mode" "$LDA_IBUS_ROOT/usr/bin/ibus" read-cache
  done | sha256sum | cut -c1-16
}

# Daemon session: start this mode's ibus-daemon on a private session bus,
# drive key events through an input context (the path every keystroke
# takes), list engines, and hash the committed text plus engine listing.
lda_ibus_session() {
  local mode="$1" keys="$2"
  IBUS_COMPONENT_PATH="$LDA_IBUS_SESSION_COMPONENTS" dbus-run-session -- \
    env LD_LIBRARY_PATH="$(lda_pkg_libdir "$mode")${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}" \
    GI_TYPELIB_PATH="$LDA_IBUS_ROOT/usr/lib/x86_64-linux-gnu/girepository-1.0${GI_TYPELIB_PATH:+:$GI_TYPELIB_PATH}" \
    python3 /opt/lda/harness/checks/ibus-keys.py "$LDA_IBUS_ROOT/usr/bin/ibus-daemon" "$LDA_IBUS_ROOT/usr/bin/ibus" "$keys" "$IBUS_FIXDIR/keys.txt" "$LDA_IBUS_ROOT/usr/libexec/ibus-memconf" \
    | sha256sum | cut -c1-16
}
