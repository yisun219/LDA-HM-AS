#!/usr/bin/env python3
from __future__ import annotations

import ctypes
import sys
from pathlib import Path


def check(root: str) -> str:
    library = next(Path(root).glob("usr/lib/*/libaio.so.1"), None)
    if library is None:
        raise SystemExit("libaio shared object missing")
    handle = ctypes.CDLL(str(library))
    return str(handle._name)


if __name__ == "__main__":
    left, right = check(sys.argv[1]), check(sys.argv[2])
    print(f"baseline={left} candidate={right}")
    raise SystemExit(left != right)
