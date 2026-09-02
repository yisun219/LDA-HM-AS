#!/usr/bin/env python3
"""Drive key events through ibus-daemon on the current session bus.

argv: ibus-daemon-path ibus-cli-path key-count keys-file config-module-path
Prints the committed text stream and the engine listing; the caller hashes it.
"""
import os, subprocess, sys, time
import gi
gi.require_version("IBus", "1.0")
from gi.repository import GLib, IBus  # noqa: E402

daemon, cli, count, keys_file, config = sys.argv[1], sys.argv[2], int(sys.argv[3]), sys.argv[4], sys.argv[5]
# The in-memory config module keeps the session hermetic (no dconf) and is
# this mode's own binary, like the engine.
proc = subprocess.Popen([daemon, "--panel=disable", "--emoji-extension=disable", "-r", "--config=" + config],
                        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
IBus.init()
bus = None
for _ in range(200):
    bus = IBus.Bus()
    if bus.is_connected():
        break
    time.sleep(0.05)
if bus is None or not bus.is_connected():
    proc.kill(); sys.exit("ibus-daemon did not come up")
with open(keys_file, encoding="utf-8") as stream:
    keys = [tuple(int(x) for x in line.split()) for line in stream if line.strip()]
committed = []
context = bus.create_input_context("lda-workbench")
context.set_capabilities(IBus.Capabilite.PREEDIT_TEXT | IBus.Capabilite.FOCUS)
context.connect("commit-text", lambda ctx, text: committed.append(text.get_text()))
context.focus_in()
context.set_engine("xkb:us::eng")
loop = GLib.MainLoop()
ctx = GLib.MainContext.default()
for index in range(count):
    keyval, keycode, state = keys[index % len(keys)]
    context.process_key_event(keyval, keycode, state)
    context.process_key_event(keyval, keycode, state | IBus.ModifierType.RELEASE_MASK)
    if index % 64 == 0:
        while ctx.pending():
            ctx.iteration(False)
deadline = time.time() + 20
while time.time() < deadline and len(committed) < 1:
    ctx.iteration(True)
end = time.time() + 0.5
while time.time() < end:
    ctx.iteration(False)
    time.sleep(0.01)
sys.stdout.write("".join(committed))
sys.stdout.write("\n")
listing = subprocess.run([cli, "list-engine"], capture_output=True, text=True)
sys.stdout.write(listing.stdout)
try:
    subprocess.run([cli, "exit"], timeout=10, capture_output=True)
except Exception:
    pass
try:
    proc.wait(timeout=10)
except Exception:
    proc.kill()
