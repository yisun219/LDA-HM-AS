#!/usr/bin/env python3
"""Unmodified ctypes consumer used by the baseline/candidate FFI fence."""

from __future__ import annotations

import ctypes
import sys
from pathlib import Path


def call(root: str) -> int:
    lib = next(Path(root).glob("usr/lib/*/libpng16.so.16"), None)
    if lib is None:
        raise SystemExit("libpng shared object missing")
    handle = ctypes.CDLL(str(lib))
    handle.png_sig_cmp.argtypes = [ctypes.c_void_p, ctypes.c_size_t, ctypes.c_size_t]
    handle.png_sig_cmp.restype = ctypes.c_int
    return int(handle.png_sig_cmp(None, 0, 0))


if __name__ == "__main__":
    left, right = call(sys.argv[1]), call(sys.argv[2])
    print(f"baseline={left} candidate={right}")
    raise SystemExit(left != right)
