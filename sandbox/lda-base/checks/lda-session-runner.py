#!/usr/bin/env python3
"""Private session + system D-Bus buses with python-dbusmock stand-ins for
the services a GNOME session daemon expects (logind, UPower, NetworkManager,
polkit, power-profiles-daemon, gnome-session), then run COMMAND inside them.

    lda-session-runner.py -- COMMAND [ARG...]
"""
import os
import subprocess
import sys

import dbus
import dbusmock


class Runner(dbusmock.DBusTestCase):
    @classmethod
    def setUpClass(cls):
        cls.start_system_bus()
        cls.start_session_bus()
        cls.procs = []
        for template, system in (("logind", True), ("upower", True), ("networkmanager", True),
                                 ("polkitd", True), ("power_profiles_daemon", True)):
            cls.procs.append(cls.spawn_server_template(template, {}, system_bus=system)[0])
        cls.procs.append(cls.spawn_server("org.gnome.SessionManager", "/org/gnome/SessionManager",
                                          "org.gnome.SessionManager", system_bus=False))
        bus = cls.get_dbus(False)
        obj = bus.get_object("org.gnome.SessionManager", "/org/gnome/SessionManager")
        mock = dbus.Interface(obj, dbusmock.MOCK_IFACE)
        mock.AddMethods("org.gnome.SessionManager", [
            ("RegisterClient", "ss", "o", 'ret = "/org/gnome/SessionManager/Client1"'),
            ("Setenv", "ss", "", ""),
            ("IsSessionRunning", "", "b", "ret = True"),
        ])
        mock.AddProperties("org.gnome.SessionManager", {"SessionIsActive": True, "SessionName": "gnome"})

    @classmethod
    def tearDownClass(cls):
        for proc in cls.procs:
            proc.terminate()
            proc.wait()
        super().tearDownClass()


def main(argv):
    if argv and argv[0] == "--":
        argv = argv[1:]
    if not argv:
        sys.exit("usage: lda-session-runner.py -- COMMAND [ARG...]")
    Runner.setUpClass()
    try:
        return subprocess.call(argv, env=dict(os.environ))
    finally:
        Runner.tearDownClass()


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
