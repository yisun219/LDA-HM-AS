#!/usr/bin/env python3
"""Start gsd plugins on the current session bus, wait until each owns its
org.gnome.SettingsDaemon.* name, stop them; repeat. argv: ITER PARALLEL PLUGIN...
Prints "LDA-GSD <sorted names>" lines and the hash of them as the last line.
"""
import hashlib
import os
import signal
import subprocess
import sys
import time

import dbus

iterations, parallel, plugins = int(sys.argv[1]), sys.argv[2] == "parallel", sys.argv[3:]
bus = dbus.SessionBus()
driver = dbus.Interface(bus.get_object("org.freedesktop.DBus", "/org/freedesktop/DBus"), "org.freedesktop.DBus")


def name_of(plugin):
    return "org.gnome.SettingsDaemon." + "".join(part.capitalize() for part in plugin.split("-"))


def wait_names(wanted, deadline):
    pending = set(wanted)
    while pending and time.time() < deadline:
        owned = set(str(n) for n in driver.ListNames())
        pending -= owned
        if pending:
            time.sleep(0.01)
    return pending


def start(plugin):
    return subprocess.Popen(["/usr/libexec/gsd-" + plugin], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def stop(procs):
    for proc in procs:
        proc.send_signal(signal.SIGTERM)
    for proc in procs:
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait()


report = []
for _ in range(iterations):
    claimed = []
    if parallel:
        procs = [start(p) for p in plugins]
        missing = wait_names([name_of(p) for p in plugins], time.time() + 20)
        claimed = sorted(name_of(p) for p in plugins if name_of(p) not in missing)
        stop(procs)
    else:
        for plugin in plugins:
            proc = start(plugin)
            missing = wait_names([name_of(plugin)], time.time() + 20)
            if not missing:
                claimed.append(name_of(plugin))
            stop([proc])
    line = "LDA-GSD " + " ".join(sorted(claimed))
    report.append(line)
    print(line)
print(hashlib.sha256("\n".join(report).encode()).hexdigest()[:16])
