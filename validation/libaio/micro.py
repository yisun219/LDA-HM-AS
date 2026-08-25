#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import math
import statistics
import sys
import time
from pathlib import Path


def main(root: str) -> int:
    library = next(Path(root).glob("usr/lib/*/libaio.so.1"), None)
    if library is None:
        raise SystemExit("libaio shared object missing")
    samples = []
    for _ in range(2):
        hashlib.sha256(library.read_bytes()).digest()
    for _ in range(7):
        start = time.perf_counter()
        for _ in range(1000):
            hashlib.sha256(library.read_bytes()).digest()
        samples.append(time.perf_counter() - start)
    median = statistics.median(samples)
    mad = statistics.median(abs(x - median) for x in samples)
    if not math.isfinite(median) or median <= 0:
        raise SystemExit("invalid benchmark result")
    print({"samples": samples, "median": median, "mad": mad})
    print(f"RESULT={median:.12f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1]))
