#!/usr/bin/env python3
"""Return success when an X11 display accepts a local UNIX connection."""

from __future__ import annotations

import socket
import sys


def main() -> int:
    display = sys.argv[1] if len(sys.argv) == 2 else ""
    if not display.startswith(":") or not display[1:].isdigit():
        return 64
    number = display[1:]
    path = f"/tmp/.X11-unix/X{number}"
    # Xorg on Linux listens on both names. E2B command mount namespaces can
    # hide the filesystem entry from the next command while the abstract
    # socket and server process remain shared, so probe both by connecting.
    for address in ("\0" + path, path):
        connection = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        connection.settimeout(0.25)
        try:
            connection.connect(address)
        except OSError:
            pass
        else:
            return 0
        finally:
            connection.close()
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
