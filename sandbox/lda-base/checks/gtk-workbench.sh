#!/usr/bin/env bash
# GTK workbench: builds the gtk-ops consumer once (dlopen, no -dev deps) and
# exposes helpers to run it against the baseline or candidate libgtk under a
# managed headless display. LDA_GTK_MAJOR selects the 4.x or 3.x card.
set -euo pipefail
. /opt/lda/harness/checks/pkg-common.sh

GTK_BENCHDIR=/opt/lda/fixtures/gtk-bench

lda_gtk_major() {
  local major="${LDA_GTK_MAJOR:?LDA_GTK_MAJOR (3 or 4) is required}"
  case "$major" in 3|4) printf '%s\n' "$major" ;; *) return 64 ;; esac
}

lda_gtk_soname() {
  case "$(lda_gtk_major)" in
    4) printf 'libgtk-4.so.1\n' ;;
    3) printf 'libgtk-3.so.0\n' ;;
  esac
}

# One shared headless display: transport only, identical for both modes.
lda_gtk_display() {
  export GDK_BACKEND=x11 GTK_A11Y=none NO_AT_BRIDGE=1 GSETTINGS_BACKEND=memory \
    LC_ALL=C XDG_RUNTIME_DIR=/tmp/lda-xdg
  mkdir -p /tmp/lda-xdg && chmod 700 /tmp/lda-xdg
  if ! test -e /tmp/.X11-unix/X77; then
    (Xvfb :77 -screen 0 1280x1024x24 -nolisten tcp >/tmp/lda-xvfb.log 2>&1 &)
    for _ in $(seq 1 50); do
      test -e /tmp/.X11-unix/X77 && break
      sleep 0.2
    done
    test -e /tmp/.X11-unix/X77 || { echo "Xvfb did not come up" >&2; return 70; }
  fi
  export DISPLAY=:77
}

lda_gtk_prepare() {
  lda_gtk_display
  mkdir -p "$GTK_BENCHDIR"
  if ! test -x "$GTK_BENCHDIR/gtk-ops"; then
    cc -O2 -Wall -o "$GTK_BENCHDIR/gtk-ops" \
      /opt/lda/harness/checks/gtk-ops.c -ldl
  fi
  test -s "${LDA_GTK_FIXDIR:-/opt/lda/fixtures/gtk}/corpus.css" || {
    echo "gtk css corpus missing; run prepare-gtk-fixtures.sh first" >&2
    return 66
  }
}

lda_gtk_attribution() {
  local mode="${1:?mode required}"
  local libdir probe major
  major="$(lda_gtk_major)"
  libdir="$(lda_pkg_libdir "$mode")"
  probe="$(mktemp)"
  lda_run_with_pkg "$mode" env LD_DEBUG=libs \
    "$GTK_BENCHDIR/gtk-ops" "$major" css-parse 1 \
    "${LDA_GTK_FIXDIR:-/opt/lda/fixtures/gtk}" >/dev/null 2>"$probe"
  grep -F "$libdir/$(lda_gtk_soname)" "$probe" >/dev/null || {
    rm -f "$probe"
    echo "gtk-ops did not load $libdir/$(lda_gtk_soname)" >&2
    return 65
  }
  rm -f "$probe"
}
