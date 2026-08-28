"""Exploration stage: evidence-based feasibility probes for ranked packages.

`lda explore <binary-package>` boots a fresh sandbox from the pinned template,
installs the STOCK package set from the recorded snapshot, exercises a
package-relevant workload with the in-sandbox nonce timer, attributes time
with perf where the sandbox allows it, and stores everything under
<results-root>/explore/<package>/. The verdict of an exploration is written
by evidence, not hope: a package whose hot code lives elsewhere is recorded
as falsified for this optimization direction, exactly like a passing one.

The probe layer is deliberately deterministic (no agent turns): exploration
answers "is there a measurable, optimizable hot path in THIS package and how
would a card benchmark it", which is a measurement task. Optimization rounds
(the RLCR loop) start only from a card, and cards are only generated for
packages whose exploration verdict supports one.
"""
from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from .cardgen import manifest_version
from .sandbox import E2BSandbox

SNAPSHOT_APT = (
    "apt-get -o Dir::Etc::sourcelist=/opt/lda/apt/snapshot.sources "
    "-o Dir::Etc::sourceparts=- -o Dir::State::lists=/opt/lda/apt/lists "
    "-o Dir::Cache=/opt/lda/apt/cache -o APT::Get::List-Cleanup=0 "
    "-o Acquire::Check-Valid-Until=false"
)

PREPARE_SOURCES = r"""
set -e
snapshot="${LDA_BASELINE_APT_SNAPSHOT:?}"
apt_root=/opt/lda/apt
mkdir -p "$apt_root/lists/partial" "$apt_root/cache/archives/partial"
cat >"$apt_root/snapshot.sources" <<EOF
Types: deb deb-src
URIs: $snapshot
Suites: resolute
Components: main restricted universe multiverse
Signed-By: /usr/share/keyrings/ubuntu-archive-keyring.gpg
EOF
APT="%(apt)s"
$APT update >/dev/null 2>&1 || $APT update >/dev/null
/opt/lda/harness/checks/align-to-snapshot.sh
sudo -n $APT install -y linux-tools-common linux-tools-generic >/dev/null 2>&1 || true
find /usr/lib -maxdepth 2 -name perf -type f 2>/dev/null | head -1 >/opt/lda/perf-path.txt || true
""" % {"apt": SNAPSHOT_APT}


@dataclass(frozen=True)
class ExploreSpec:
    """One package's probe recipe. `workload` may be empty for analysis-only."""

    package: str
    source: str
    # Snapshot packages installed before the workload (space separated).
    install: str = ""
    # Bash text: exercises the package's own code path and prints one or more
    # nonce-tagged LDA_BENCH samples (pkg-common.sh is already sourced).
    workload: str = ""
    # Command line whose execution perf should attribute (defaults: none).
    profile_command: str = ""
    # Analysis-only notes evaluated in the report when no workload exists.
    composition_note: str = ""
    timeout_seconds: int = 2400


LIBRARY: dict[str, ExploreSpec] = {}


def _spec(spec: ExploreSpec) -> ExploreSpec:
    LIBRARY[spec.package] = spec
    return spec


_spec(ExploreSpec(
    package="libgtk-4-1",
    source="gtk4",
    install=(
        "libgtk-4-1 gir1.2-gtk-4.0 python3-gi fontconfig fonts-dejavu-core "
        "dbus-x11 adwaita-icon-theme shared-mime-info"
    ),
    workload=r"""
cat >/opt/lda/explore/gtk4-widgets.py <<'PYW'
import gi, os, sys, time, hashlib
gi.require_version("Gtk", "4.0")
from gi.repository import Gtk
os.environ.setdefault("GDK_BACKEND", "x11")
app = Gtk.Application(application_id="lda.explore.gtk4")
result = {}
def on_activate(app):
    window = Gtk.ApplicationWindow(application=app)
    digest = hashlib.sha256()
    start = time.perf_counter_ns()
    for round_number in range(40):
        grid = Gtk.Grid()
        for index in range(300):
            label = Gtk.Label(label=f"item {round_number}-{index}")
            label.add_css_class("title-2" if index % 3 else "dim-label")
            grid.attach(label, index % 20, index // 20, 1, 1)
        window.set_child(grid)
        minimum, natural, b1, b2 = grid.measure(Gtk.Orientation.HORIZONTAL, -1)
        digest.update(f"{minimum}:{natural}".encode())
    result["seconds"] = (time.perf_counter_ns() - start) / 1e9
    result["hash"] = digest.hexdigest()[:16]
    app.quit()
app.connect("activate", on_activate)
app.run(None)
print(f"WIDGET_SECONDS={result['seconds']:.6f}", file=sys.stderr)
print(result["hash"])
PYW
xvfb-run -a python3 /opt/lda/explore/gtk4-widgets.py >/dev/null
lda_bench_run micro gtk4-widget-churn stock 40 \
  xvfb-run -a python3 /opt/lda/explore/gtk4-widgets.py
""",
    profile_command="xvfb-run -a python3 /opt/lda/explore/gtk4-widgets.py",
))

_spec(ExploreSpec(
    package="libgtk-3-0t64",
    source="gtk+3.0",
    install=(
        "libgtk-3-0t64 gir1.2-gtk-3.0 python3-gi fontconfig fonts-dejavu-core "
        "dbus-x11 adwaita-icon-theme shared-mime-info"
    ),
    workload=r"""
cat >/opt/lda/explore/gtk3-widgets.py <<'PYW'
import gi, sys, time, hashlib
gi.require_version("Gtk", "3.0")
from gi.repository import Gtk
digest = hashlib.sha256()
start = time.perf_counter_ns()
for round_number in range(40):
    window = Gtk.OffscreenWindow()
    grid = Gtk.Grid()
    for index in range(300):
        label = Gtk.Label(label=f"item {round_number}-{index}")
        grid.attach(label, index % 20, index // 20, 1, 1)
    window.add(grid)
    window.show_all()
    minimum, natural = grid.get_preferred_width()
    digest.update(f"{minimum}:{natural}".encode())
    window.destroy()
seconds = (time.perf_counter_ns() - start) / 1e9
print(f"WIDGET_SECONDS={seconds:.6f}", file=sys.stderr)
print(digest.hexdigest()[:16])
PYW
xvfb-run -a python3 /opt/lda/explore/gtk3-widgets.py >/dev/null
lda_bench_run micro gtk3-widget-churn stock 40 \
  xvfb-run -a python3 /opt/lda/explore/gtk3-widgets.py
""",
    profile_command="xvfb-run -a python3 /opt/lda/explore/gtk3-widgets.py",
))

_spec(ExploreSpec(
    package="libsoup-3.0-0",
    source="libsoup3",
    install="libsoup-3.0-0 gir1.2-soup-3.0 python3-gi ca-certificates",
    workload=r"""
cat >/opt/lda/explore/soup-client.py <<'PYW'
import gi, sys, time, hashlib
gi.require_version("Soup", "3.0")
from gi.repository import Soup, GLib
base = sys.argv[1]
session = Soup.Session()
digest = hashlib.sha256()
start = time.perf_counter_ns()
for index in range(600):
    message = Soup.Message.new("GET", f"{base}/item/{index}")
    request_headers = message.get_request_headers()
    request_headers.append("X-Trace", f"probe-{index}")
    request_headers.append("Accept", "text/plain, application/json;q=0.9, */*;q=0.1")
    body = session.send_and_read(message, None)
    response_headers = message.get_response_headers()
    digest.update(bytes(body.get_data() or b""))
    digest.update(str(response_headers.get_one("Content-Type")).encode())
seconds = (time.perf_counter_ns() - start) / 1e9
print(digest.hexdigest()[:16])
print(f"HTTP_SECONDS={seconds:.6f}", file=sys.stderr)
PYW
cat >/opt/lda/explore/soup-server.py <<'PYW'
from http.server import BaseHTTPRequestHandler, HTTPServer
import threading, sys
PAYLOAD = (b"payload-" * 96)[:512]
class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        self.send_header("Cache-Control", "max-age=60, public")
        self.send_header("X-Answer", self.path[-40:])
        self.send_header("Content-Length", str(len(PAYLOAD)))
        self.end_headers()
        self.wfile.write(PAYLOAD)
    def log_message(self, *args):
        pass
server = HTTPServer(("127.0.0.1", 0), Handler)
print(server.server_port, flush=True)
server.serve_forever()
PYW
python3 /opt/lda/explore/soup-server.py >/opt/lda/explore/soup-port.txt &
server_pid=$!
sleep 1
port="$(head -1 /opt/lda/explore/soup-port.txt)"
lda_bench_run micro soup-http-churn stock 600 \
  python3 /opt/lda/explore/soup-client.py "http://127.0.0.1:$port"
kill "$server_pid" 2>/dev/null || true
""",
    profile_command="",
))

_spec(ExploreSpec(
    package="gstreamer1.0-plugins-good",
    source="gst-plugins-good1.0",
    install=(
        "gstreamer1.0-tools gstreamer1.0-plugins-base gstreamer1.0-plugins-good"
    ),
    workload=r"""
export GST_REGISTRY=/opt/lda/explore/gst-registry.bin
gst-launch-1.0 -q videotestsrc num-buffers=420 pattern=ball ! video/x-raw,width=1280,height=720 ! vp8enc deadline=1 ! matroskamux ! filesink location=/opt/lda/explore/sample.mkv
gst-launch-1.0 -q audiotestsrc num-buffers=4000 ! audio/x-raw,rate=44100,channels=2 ! wavenc ! filesink location=/opt/lda/explore/sample.wav
gst-launch-1.0 -q filesrc location=/opt/lda/explore/sample.wav ! wavparse ! flacenc ! filesink location=/opt/lda/explore/sample.flac
decode_all() {
  gst-launch-1.0 -q filesrc location=/opt/lda/explore/sample.mkv ! matroskademux ! vp8dec ! fakesink sync=false
  gst-launch-1.0 -q filesrc location=/opt/lda/explore/sample.flac ! flacparse ! flacdec ! fakesink sync=false
  gst-launch-1.0 -q filesrc location=/opt/lda/explore/sample.wav ! wavparse ! fakesink sync=false
  sha256sum /opt/lda/explore/sample.mkv | cut -c1-16
}
decode_all >/dev/null 2>&1
lda_bench_run micro gst-good-decode stock 6 sh -c 'gst-launch-1.0 -q filesrc location=/opt/lda/explore/sample.mkv ! matroskademux ! vp8dec ! fakesink sync=false 2>/dev/null; gst-launch-1.0 -q filesrc location=/opt/lda/explore/sample.flac ! flacparse ! flacdec ! fakesink sync=false 2>/dev/null; sha256sum /opt/lda/explore/sample.mkv | cut -c1-16'
""",
    profile_command=(
        "env GST_REGISTRY=/opt/lda/explore/gst-registry.bin gst-launch-1.0 -q "
        "filesrc location=/opt/lda/explore/sample.mkv ! matroskademux ! vp8dec "
        "! fakesink sync=false"
    ),
))

_spec(ExploreSpec(
    package="libcairo2",
    source="cairo",
    install="libcairo2 python3-pil",
    workload=r"""
python3 - <<'PYW'
from PIL import Image
import random
random.seed(2604)
image = Image.new("RGB", (1600, 1200))
image.putdata([(random.randrange(256), random.randrange(256), random.randrange(256)) for _ in range(1600 * 1200)])
image.save("/opt/lda/explore/deck.png", compress_level=6)
PYW
cat >/opt/lda/explore/cairo-load.c <<'CW'
#include <dlfcn.h>
#include <stdio.h>
int main(int argc, char **argv) {
  void *so = dlopen("libcairo.so.2", RTLD_NOW);
  void *(*from_png)(const char *) = dlsym(so, "cairo_image_surface_create_from_png");
  void (*destroy)(void *) = dlsym(so, "cairo_surface_destroy");
  int (*status)(void *) = dlsym(so, "cairo_surface_status");
  for (int i = 0; i < 24; ++i) {
    void *s = from_png(argv[1]);
    if (!s || status(s)) return 2;
    destroy(s);
  }
  puts("ok-24");
  return 0;
}
CW
cc -O2 -o /opt/lda/explore/cairo-load /opt/lda/explore/cairo-load.c
lda_bench_run micro cairo-png-surface stock 24 sh -c '/opt/lda/explore/cairo-load /opt/lda/explore/deck.png'
""",
    profile_command="/opt/lda/explore/cairo-load /opt/lda/explore/deck.png",
))

_spec(ExploreSpec(
    package="gnome-shell",
    source="gnome-shell",
    install="",
    composition_note=(
        "compositor frame loop lives in libmutter/clutter, JS in gjs/SpiderMonkey, "
        "startup path dominated by gjs and library loading; the gnome-shell "
        "package's own compiled code is a thin layer over those"
    ),
))

_spec(ExploreSpec(
    package="libreoffice-core",
    source="libreoffice",
    install="",
    composition_note=(
        "measurable end to end (soffice --headless --convert-to pdf), but a "
        "candidate rebuild of libreoffice inside one sandbox round costs hours, "
        "so per-round paired rebuild benchmarking is not operable on the "
        "current template"
    ),
))

_spec(ExploreSpec(
    package="sssd-common",
    source="sssd",
    install="",
    composition_note=(
        "hot paths are NSS/PAM lookups against a directory service; a rigorous "
        "benchmark needs an LDAP/Kerberos fixture harness the template does "
        "not ship"
    ),
))

_spec(ExploreSpec(
    package="gnome-settings-daemon",
    source="gnome-settings-daemon",
    install="",
    composition_note=(
        "per-plugin daemons need a live GNOME session bus and portal stack; "
        "startup micro is measurable headlessly only for a subset of plugins"
    ),
))

_spec(ExploreSpec(
    package="ibus",
    source="ibus",
    install="",
    composition_note=(
        "input path latency spans ibus-daemon, dbus and the client GTK "
        "immodule; the daemon's own compiled hot path is thin glue and the "
        "benchmarkable path needs a focused-window fixture"
    ),
))

IDENTITY_SCRIPT = r"""
set -e
mkdir -p /opt/lda/explore
{
  echo "## kernel"; uname -a
  echo "## nproc"; nproc
  echo "## flags"; grep -m1 flags /proc/cpuinfo | tr ' ' '\n' | grep -E 'avx|sse4|amx|bmi|adx|vaes|gfni|sha' | sort | tr '\n' ' '; echo
  echo "## model"; grep -m1 "model name" /proc/cpuinfo || true
  echo "## perf_event_paranoid"; cat /proc/sys/kernel/perf_event_paranoid 2>/dev/null || echo unavailable
  perf_binary="$(cat /opt/lda/perf-path.txt 2>/dev/null || true)"
  test -n "$perf_binary" || perf_binary=perf
  echo "## perf binary"; echo "$perf_binary"
  echo "## perf hw"; timeout 20 "$perf_binary" stat -e cycles,instructions -- sleep 0.05 2>&1 | tail -4 || true
  echo "## perf sw"; timeout 20 "$perf_binary" stat -e task-clock -- sleep 0.05 2>&1 | tail -3 || true
} >/opt/lda/explore/identity.txt 2>&1
cat /opt/lda/explore/identity.txt
"""


def explore(
    package: str,
    results_root: Path,
    *,
    baseline: dict,
    assets_root: Path,
    template: Optional[str] = None,
) -> Path:
    spec = LIBRARY.get(package)
    if spec is None:
        raise SystemExit(f"no exploration spec for {package}; add it to explore.LIBRARY")
    version = manifest_version(package) or ""
    out = results_root / "explore" / package
    out.mkdir(parents=True, exist_ok=True)
    record: dict = {
        "package": package,
        "source": spec.source,
        "manifest_version": version,
        "snapshot": baseline.get("apt_snapshot", ""),
        "started_epoch": time.time(),
        "steps": [],
    }

    def run_step(name: str, sandbox, command, timeout: int = 1200) -> bool:
        result = sandbox.run(command, timeout_seconds=timeout)
        record["steps"].append(
            {
                "name": name,
                "exit": result.exit_code,
                "stdout": result.stdout[-8000:],
                "stderr": result.stderr[-4000:],
            }
        )
        (out / f"{name}.txt").write_text(
            f"exit={result.exit_code}\n--- stdout ---\n{result.stdout}"
            f"\n--- stderr ---\n{result.stderr}\n",
            encoding="utf-8",
        )
        return result.ok

    if not spec.workload:
        # Analysis-only exploration: record the composition verdict without a
        # sandbox; the mechanical facts (version, snapshot) are still pinned.
        record["mode"] = "analysis-only"
        record["composition_note"] = spec.composition_note
        (out / "exploration.json").write_text(
            json.dumps(record, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
        return out

    record["mode"] = "sandbox-workload"
    sandbox = E2BSandbox.connect(template=template or baseline.get("template", "lda-base"), timeout=7200)
    record["sandbox_id"] = sandbox.sandbox_id
    try:
        sandbox.bootstrap_assets(assets_root)
        env = ("env", "LDA_BASELINE_APT_SNAPSHOT=" + baseline.get("apt_snapshot", ""))
        if not run_step("sources", sandbox, env + ("bash", "-c", PREPARE_SOURCES), 900):
            return out
        if spec.install:
            install = (
                f"sudo -n {SNAPSHOT_APT} install -y --allow-downgrades {spec.install}"
            )
            if not run_step("install", sandbox, ("bash", "-c", install), 1800):
                return out
        run_step("identity", sandbox, ("bash", "-c", IDENTITY_SCRIPT), 300)
        workload = (
            "set -eo pipefail\n. /opt/lda/harness/checks/pkg-common.sh\n"
            "mkdir -p /opt/lda/explore\ncd /opt/lda/explore\n" + spec.workload
        )
        run_step("workload", sandbox, ("bash", "-c", workload), spec.timeout_seconds)
        if spec.profile_command:
            profile = (
                'perf_binary="$(cat /opt/lda/perf-path.txt 2>/dev/null)"; '
                'test -n "$perf_binary" || perf_binary=perf; '
                "cd /opt/lda/explore && "
                f'timeout 600 "$perf_binary" record -q --freq 400 -o perf.data -- {spec.profile_command} '
                ">/dev/null; "
                '"$perf_binary" report -i perf.data --stdio --sort dso --percent-limit 1 2>/dev/null | head -25; '
                "echo '--- top symbols ---'; "
                '"$perf_binary" report -i perf.data --stdio --sort dso,symbol --percent-limit 2 2>/dev/null | head -40'
            )
            run_step("profile", sandbox, ("bash", "-c", profile), 900)
    finally:
        record["finished_epoch"] = time.time()
        (out / "exploration.json").write_text(
            json.dumps(record, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
        sandbox.close()
    return out
