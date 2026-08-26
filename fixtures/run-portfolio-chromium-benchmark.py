#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import random
import subprocess
import tempfile
import time
from pathlib import Path


def install(mode: str) -> None:
    packages = sorted(Path(f"/opt/lda/packages/{mode}").glob("*.deb"))
    if not packages:
        raise RuntimeError(f"no {mode} packages")
    subprocess.run(
        ["sudo", "/usr/bin/dpkg", "-i", *map(str, packages)],
        check=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
        text=True,
    )
    subprocess.run(["sudo", "/usr/bin/dpkg", "--audit"], check=True)


def render(page: Path, cpu: str) -> float:
    command = [
        "taskset",
        "-c",
        cpu,
        "chromium",
        "--headless",
        "--no-sandbox",
        "--disable-gpu",
        "--disable-background-networking",
        "--disable-component-update",
        "--disable-sync",
        "--metrics-recording-only",
        "--virtual-time-budget=1500",
        "--dump-dom",
        page.as_uri(),
    ]
    started = time.perf_counter_ns()
    completed = subprocess.run(
        command,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        timeout=60,
    )
    elapsed = (time.perf_counter_ns() - started) / 1_000_000_000
    if completed.returncode != 0 or "LDA_RENDER_COMPLETE" not in completed.stdout:
        raise RuntimeError(completed.stderr[-1000:])
    return elapsed


def main() -> None:
    affinity = str(min(os.sched_getaffinity(0)))
    rng = random.Random(2604)
    html = """<!doctype html><meta charset=utf-8><title>LDA</title>
<canvas id=c width=1600 height=900></canvas><div id=result></div><script>
const c=document.getElementById('c'),x=c.getContext('2d');
for(let frame=0;frame<120;frame++){
  x.clearRect(0,0,c.width,c.height);
  for(let i=0;i<1200;i++){
    x.fillStyle=`rgb(${(i*17+frame)%255},${(i*29)%255},${(i*43)%255})`;
    x.fillRect((i*37)%1600,(i*53)%900,8+(i%32),8+((i*3)%32));
  }
}
document.getElementById('result').textContent='LDA_RENDER_COMPLETE';
</script>"""
    with tempfile.TemporaryDirectory() as directory:
        page = Path(directory) / "portfolio.html"
        page.write_text(html, encoding="utf-8")
        for mode in ("baseline", "candidate"):
            install(mode)
            for _ in range(10):
                render(page, affinity)
        baseline: list[float] = []
        candidate: list[float] = []
        order: list[str] = []
        for _ in range(30):
            first = "baseline" if rng.randrange(2) == 0 else "candidate"
            order.append(first)
            values: dict[str, float] = {}
            for mode in (first, "candidate" if first == "baseline" else "baseline"):
                install(mode)
                values[mode] = render(page, affinity)
            baseline.append(values["baseline"])
            candidate.append(values["candidate"])
        install("baseline")
    cpu = subprocess.check_output(
        "lscpu | sed -n 's/^Model name:[[:space:]]*//p'", shell=True, text=True
    ).strip()
    print(json.dumps({
        "name": "portfolio-chromium-canvas",
        "layer": "e2e",
        "baseline": baseline,
        "candidate": candidate,
        "warmups": 10,
        "seed": 2604,
        "randomized_order": order,
        "scenario_ids": ["workload=chromium-canvas-1600x900x120"] * 30,
        "cpu_affinity": affinity,
        "numa_policy": "local",
        "environment": {
            "cpu": cpu,
            "kernel": subprocess.check_output(["uname", "-r"], text=True).strip(),
            "workload": "Chromium Canvas 1600x900x120 frames",
        },
    }))


if __name__ == "__main__":
    main()
