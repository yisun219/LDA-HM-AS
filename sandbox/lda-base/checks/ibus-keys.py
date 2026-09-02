#!/usr/bin/env python3
"""Drive key events through ibus-daemon on the current session bus.

argv: ibus-daemon-path ibus-cli-path key-count keys-file config-module-path
Prints the committed text stream, the handled-event count and the engine
listing; the caller hashes it. This is the path every keystroke takes on a
desktop: client -> daemon -> engine (ibus-engine-simple, with its compose
tables) -> client.
"""
import os
import subprocess
import sys
import time

import gi

gi.require_version("IBus", "1.0")
from gi.repository import GLib, IBus  # noqa: E402

daemon, cli, count, keys_file, config = sys.argv[1], sys.argv[2], int(sys.argv[3]), sys.argv[4], sys.argv[5]
# The in-memory config module keeps the session hermetic (no dconf) and is
# this mode's own binary, like the engine.
proc = subprocess.Popen([daemon, "--panel=disable", "--emoji-extension=disable", "--config=" + config],
                        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
IBus.init()
# A Bus created before the daemon has published its address never recovers,
# so wait for the address file and its socket first.
deadline = time.time() + 20
address = None
while time.time() < deadline:
    address = IBus.get_address()
    if address and os.path.exists(address.split("unix:path=", 1)[1].split(",")[0]):
        break
    time.sleep(0.02)
time.sleep(0.2)
bus = IBus.Bus()
if not bus.is_connected():
    proc.kill()
    sys.exit("ibus-daemon did not come up")
with open(keys_file, encoding="utf-8") as stream:
    keys = [tuple(int(x) for x in line.split()) for line in stream if line.strip()]
committed = []
context = bus.create_input_context("lda-workbench")
context.set_capabilities(IBus.Capabilite.PREEDIT_TEXT | IBus.Capabilite.FOCUS)
context.connect("commit-text", lambda ctx, text: committed.append(text.get_text()))
context.focus_in()
context.set_engine("xkb:us::eng")
main = GLib.MainContext.default()
settle = time.time() + 0.8
while time.time() < settle:
    main.iteration(False)
    time.sleep(0.005)
handled = 0
for index in range(count):
    keyval, keycode, state = keys[index % len(keys)]
    if context.process_key_event(keyval, keycode, state):
        handled += 1
    context.process_key_event(keyval, keycode, state | IBus.ModifierType.RELEASE_MASK)
    if index % 32 == 0:
        while main.pending():
            main.iteration(False)
end = time.time() + 1.0
while time.time() < end:
    main.iteration(False)
    time.sleep(0.005)
sys.stdout.write("".join(committed) + "\n")
sys.stdout.write(f"handled={handled} committed={len(committed)}\n")
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
