#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import random
import subprocess
import time
from pathlib import Path


def duration(binary: Path, libdir: str, loops: int, affinity: str) -> float:
    env = {**os.environ, "LD_LIBRARY_PATH": libdir}
    started = time.perf_counter_ns()
    subprocess.run(["taskset", "-c", affinity, str(binary), str(loops)], env=env, check=True, stdout=subprocess.DEVNULL)
    return (time.perf_counter_ns() - started) / 1_000_000_000


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--layer", choices=("micro", "e2e"), required=True)
    parser.add_argument("--name", required=True)
    parser.add_argument("--loops", type=int, default=100000)
    parser.add_argument("--seed", type=int, default=2604)
    parser.add_argument("--affinity", default="0")
    args = parser.parse_args()
    binary = Path("/opt/lda/fixtures/generic/probe")
    baseline_libdir = str(Path(Path("/opt/lda/baseline/libraries.list").read_text().splitlines()[0]).parent)
    candidate_libdir = str(Path(Path("/opt/lda/candidate/libraries.list").read_text().splitlines()[0]).parent)
    for _ in range(10):
        duration(binary, baseline_libdir, args.loops, args.affinity)
        duration(binary, candidate_libdir, args.loops, args.affinity)
    rng = random.Random(args.seed)
    baseline: list[float] = []
    candidate: list[float] = []
    order: list[str] = []
    for _ in range(30):
        first = "baseline" if rng.randrange(2) == 0 else "candidate"
        order.append(first)
        values = {}
        for mode in (first, "candidate" if first == "baseline" else "baseline"):
            values[mode] = duration(binary, baseline_libdir if mode == "baseline" else candidate_libdir, args.loops, args.affinity)
        baseline.append(values["baseline"])
        candidate.append(values["candidate"])
    environment = {
        "kernel": subprocess.check_output(["uname", "-r"], text=True).strip(),
        "cpu": subprocess.check_output("lscpu | sed -n 's/^Model name:[[:space:]]*//p'", shell=True, text=True).strip(),
        "microcode": Path("/proc/cpuinfo").read_text().split("microcode", 1)[-1].splitlines()[0] if "microcode" in Path("/proc/cpuinfo").read_text() else "unknown",
        "governor": Path("/sys/devices/system/cpu/cpu0/cpufreq/scaling_governor").read_text().strip() if Path("/sys/devices/system/cpu/cpu0/cpufreq/scaling_governor").exists() else "unavailable",
    }
    print(json.dumps({
        "name": args.name,
        "layer": args.layer,
        "baseline": baseline,
        "candidate": candidate,
        "warmups": 10,
        "seed": args.seed,
        "randomized_order": order,
        "cpu_affinity": args.affinity,
        "numa_policy": "local",
        "environment": environment,
    }))


if __name__ == "__main__":
    main()
