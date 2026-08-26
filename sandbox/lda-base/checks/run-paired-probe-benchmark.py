#!/usr/bin/env python3
from __future__ import annotations

import argparse
import concurrent.futures
import json
import math
import os
import random
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path


EVICTION_BUFFER = bytearray(128 * 1024 * 1024)


@dataclass(frozen=True)
class Scenario:
    input_size: int
    distribution: str
    cache_mode: str
    concurrency: int

    @property
    def scenario_id(self) -> str:
        return (
            f"input={self.input_size};distribution={self.distribution};"
            f"cache={self.cache_mode};concurrency={self.concurrency}"
        )


def _read(path: str, default: str = "unavailable") -> str:
    candidate = Path(path)
    return candidate.read_text().strip() if candidate.exists() else default


def _cpu_topology() -> tuple[list[str], str]:
    allowed = set(os.sched_getaffinity(0))
    rows = subprocess.check_output(["lscpu", "-p=CPU,NODE"], text=True)
    by_node: dict[str, list[int]] = {}
    for row in rows.splitlines():
        if not row or row.startswith("#"):
            continue
        cpu_text, node = row.split(",", 1)
        cpu = int(cpu_text)
        if cpu in allowed:
            by_node.setdefault(node, []).append(cpu)
    candidates = sorted(by_node.items(), key=lambda item: (-len(item[1]), int(item[0])))
    if not candidates or len(candidates[0][1]) < 2:
        raise RuntimeError("micro benchmark requires two allowed CPUs on one NUMA node")
    node, cpus = candidates[0]
    return [str(cpu) for cpu in sorted(cpus)[:2]], node


def _evict_cpu_cache() -> None:
    for offset in range(0, len(EVICTION_BUFFER), 64):
        EVICTION_BUFFER[offset] = (EVICTION_BUFFER[offset] + 1) & 0xFF


def _probe(
    binary: Path,
    libdir: str,
    loops: int,
    scenario: Scenario,
    cpu: str,
    seed: int,
    *,
    capture: bool = False,
) -> str:
    env = {**os.environ, "LD_LIBRARY_PATH": libdir}
    completed = subprocess.run(
        [
            "taskset",
            "-c",
            cpu,
            str(binary),
            str(loops),
            scenario.distribution,
            str(scenario.input_size),
            str(seed),
        ],
        env=env,
        check=True,
        stdout=subprocess.PIPE if capture else subprocess.DEVNULL,
        stderr=subprocess.PIPE,
        text=True,
    )
    return completed.stdout.strip() if capture else ""


def _duration(
    binary: Path,
    libdir: str,
    loops: int,
    scenario: Scenario,
    cpus: list[str],
    seed: int,
) -> float:
    if scenario.cache_mode == "cold":
        _evict_cpu_cache()
    worker_loops = max(1, math.ceil(loops / scenario.concurrency))
    started = time.perf_counter_ns()
    if scenario.concurrency == 1:
        _probe(binary, libdir, worker_loops, scenario, cpus[0], seed)
    else:
        with concurrent.futures.ThreadPoolExecutor(
            max_workers=scenario.concurrency
        ) as executor:
            futures = [
                executor.submit(
                    _probe,
                    binary,
                    libdir,
                    worker_loops,
                    scenario,
                    cpus[index],
                    seed + index,
                )
                for index in range(scenario.concurrency)
            ]
            for future in futures:
                future.result()
    return (time.perf_counter_ns() - started) / 1_000_000_000


def _scenario_matrix(input_sizes: list[int]) -> list[Scenario]:
    if len(input_sizes) < 3 or len(set(input_sizes)) < 3:
        raise ValueError("at least three distinct input sizes are required")
    small, medium, large = sorted(set(input_sizes))[:3]
    return [
        Scenario(small, "sequential", "hot", 1),
        Scenario(medium, "random", "hot", 1),
        Scenario(large, "alternating", "cold", 1),
        Scenario(small, "random", "cold", 2),
        Scenario(medium, "sequential", "hot", 2),
        Scenario(large, "alternating", "hot", 2),
        Scenario(large, "random", "cold", 1),
        Scenario(small, "alternating", "cold", 2),
    ]


def _verify_outputs(
    binary: Path,
    baseline_libdir: str,
    candidate_libdir: str,
    scenarios: list[Scenario],
    cpu: str,
    seed: int,
) -> None:
    checked: set[tuple[int, str]] = set()
    for scenario in scenarios:
        identity = (scenario.input_size, scenario.distribution)
        if identity in checked:
            continue
        checked.add(identity)
        baseline = _probe(
            binary, baseline_libdir, 257, scenario, cpu, seed, capture=True
        )
        candidate = _probe(
            binary, candidate_libdir, 257, scenario, cpu, seed, capture=True
        )
        if baseline != candidate:
            raise RuntimeError(
                "candidate output differs from baseline for "
                f"input={scenario.input_size}, distribution={scenario.distribution}"
            )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--layer", choices=("micro", "e2e"), required=True)
    parser.add_argument("--name", required=True)
    parser.add_argument("--loops", type=int, default=100000)
    parser.add_argument("--input-sizes", default="16,64,256")
    parser.add_argument("--seed", type=int, default=2604)
    args = parser.parse_args()
    input_sizes = [int(value) for value in args.input_sizes.split(",") if value]
    scenarios = (
        _scenario_matrix(input_sizes)
        if args.layer == "micro"
        else [Scenario(sorted(set(input_sizes))[1], "sequential", "hot", 1)]
    )
    cpus, numa_node = _cpu_topology()
    binary = Path("/opt/lda/fixtures/generic/probe")
    baseline_libdir = str(
        Path(Path("/opt/lda/baseline/libraries.list").read_text().splitlines()[0]).parent
    )
    candidate_libdir = str(
        Path(Path("/opt/lda/candidate/libraries.list").read_text().splitlines()[0]).parent
    )
    _verify_outputs(
        binary, baseline_libdir, candidate_libdir, scenarios, cpus[0], args.seed
    )

    for index in range(10):
        scenario = scenarios[index % len(scenarios)]
        _duration(binary, baseline_libdir, args.loops, scenario, cpus, args.seed + index)
        _duration(binary, candidate_libdir, args.loops, scenario, cpus, args.seed + index)

    rng = random.Random(args.seed)
    sample_scenarios = [scenarios[index % len(scenarios)] for index in range(30)]
    rng.shuffle(sample_scenarios)
    baseline: list[float] = []
    candidate: list[float] = []
    order: list[str] = []
    scenario_ids: list[str] = []
    for index, scenario in enumerate(sample_scenarios):
        first = "baseline" if rng.randrange(2) == 0 else "candidate"
        order.append(first)
        scenario_ids.append(scenario.scenario_id)
        values: dict[str, float] = {}
        for mode in (first, "candidate" if first == "baseline" else "baseline"):
            values[mode] = _duration(
                binary,
                baseline_libdir if mode == "baseline" else candidate_libdir,
                args.loops,
                scenario,
                cpus,
                args.seed + index,
            )
        baseline.append(values["baseline"])
        candidate.append(values["candidate"])

    cpuinfo = Path("/proc/cpuinfo").read_text()
    environment = {
        "kernel": subprocess.check_output(["uname", "-r"], text=True).strip(),
        "cpu": subprocess.check_output(
            "lscpu | sed -n 's/^Model name:[[:space:]]*//p'", shell=True, text=True
        ).strip(),
        "microcode": (
            cpuinfo.split("microcode", 1)[-1].splitlines()[0].lstrip("\t: ")
            if "microcode" in cpuinfo
            else "unknown"
        ),
        "governor": _read(
            f"/sys/devices/system/cpu/cpu{cpus[0]}/cpufreq/scaling_governor"
        ),
        "turbo_disabled": _read("/sys/devices/system/cpu/intel_pstate/no_turbo"),
        "load_average": _read("/proc/loadavg"),
        "scenario_matrix": json.dumps(
            [scenario.scenario_id for scenario in scenarios], separators=(",", ":")
        ),
    }
    print(
        json.dumps(
            {
                "name": args.name,
                "layer": args.layer,
                "baseline": baseline,
                "candidate": candidate,
                "warmups": 10,
                "seed": args.seed,
                "randomized_order": order,
                "scenario_ids": scenario_ids,
                "cpu_affinity": ",".join(cpus),
                "numa_policy": f"node:{numa_node}",
                "environment": environment,
            }
        )
    )


if __name__ == "__main__":
    main()
