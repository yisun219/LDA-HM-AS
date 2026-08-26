#!/usr/bin/env python3
from __future__ import annotations

import http.server
import json
import os
import random
import socketserver
import subprocess
import threading
import time
from pathlib import Path


class Handler(http.server.BaseHTTPRequestHandler):
    payload = b"x" * 4096

    def do_GET(self) -> None:  # noqa: N802
        self.send_response(200)
        self.send_header("Content-Type", "application/octet-stream")
        self.send_header("Content-Length", str(len(self.payload)))
        self.end_headers()
        self.wfile.write(self.payload)

    def log_message(self, _format: str, *_args: object) -> None:
        return


def duration(libdir: str, loops: int, port: int, affinity: str) -> float:
    env = {**os.environ, "LD_LIBRARY_PATH": libdir}
    command = [
        "taskset", "-c", affinity, "/opt/lda/fixtures/libsoup-e2e", str(loops),
        f"http://127.0.0.1:{port}/payload",
    ]
    started = time.perf_counter_ns()
    subprocess.run(command, env=env, check=True, stdout=subprocess.DEVNULL)
    return (time.perf_counter_ns() - started) / 1_000_000_000


def main() -> None:
    affinity = str(min(os.sched_getaffinity(0)))
    baseline = str(Path(Path("/opt/lda/baseline/libraries.list").read_text().splitlines()[0]).parent)
    candidate = str(Path(Path("/opt/lda/candidate/libraries.list").read_text().splitlines()[0]).parent)
    with socketserver.ThreadingTCPServer(("127.0.0.1", 0), Handler) as server:
        port = int(server.server_address[1])
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        for _ in range(10):
            duration(baseline, 100, port, affinity)
            duration(candidate, 100, port, affinity)
        rng = random.Random(2604)
        baseline_samples: list[float] = []
        candidate_samples: list[float] = []
        order: list[str] = []
        for _ in range(30):
            first = "baseline" if rng.randrange(2) == 0 else "candidate"
            order.append(first)
            values = {}
            for mode in (first, "candidate" if first == "baseline" else "baseline"):
                values[mode] = duration(baseline if mode == "baseline" else candidate, 100, port, affinity)
            baseline_samples.append(values["baseline"])
            candidate_samples.append(values["candidate"])
        server.shutdown()
    print(json.dumps({
        "name": "libsoup-local-http-e2e",
        "layer": "e2e",
        "baseline": baseline_samples,
        "candidate": candidate_samples,
        "warmups": 10,
        "seed": 2604,
        "randomized_order": order,
        "scenario_ids": ["workload=local-http-4k;mode=synchronous"] * 30,
        "cpu_affinity": affinity,
        "numa_policy": "local",
        "environment": {
            "kernel": subprocess.check_output(["uname", "-r"], text=True).strip(),
            "cpu": subprocess.check_output("lscpu | sed -n 's/^Model name:[[:space:]]*//p'", shell=True, text=True).strip(),
            "workload": "libsoup synchronous HTTP client against local 4 KiB web server",
        },
    }))


if __name__ == "__main__":
    main()
