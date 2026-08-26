#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import http.server
import json
import math
import os
import platform
import shutil
import socketserver
import subprocess
import sys
import threading
import time
import urllib.request
from contextlib import contextmanager
from pathlib import Path

SCHEMA = "lda.portfolio-e2e.v1"
KINDS = {"web_server", "chrome_gui"}
SECRET_MARKERS = ("KEY", "TOKEN", "SECRET", "PASSWORD", "CREDENTIAL")


def validate(raw):
    if not isinstance(raw, dict): raise ValueError("config must be an object")
    warmups, samples = raw.get("warmups", 2), raw.get("samples", 5)
    if not isinstance(warmups, int) or not 0 <= warmups <= 20: raise ValueError("invalid warmups")
    if not isinstance(samples, int) or not 2 <= samples <= 50: raise ValueError("invalid samples")
    variants = {}
    for name in ("baseline", "candidate"):
        value = raw.get(name)
        if not isinstance(value, dict): raise ValueError(f"missing {name}")
        root = Path(value.get("document_root", "")).resolve()
        if not root.is_dir(): raise ValueError(f"invalid {name} document_root")
        env = value.get("env", {})
        if not isinstance(env, dict) or any(not isinstance(k, str) or not isinstance(v, str) for k, v in env.items()):
            raise ValueError(f"invalid {name} env")
        if set(env) - {"LD_LIBRARY_PATH"} or any(any(x in key.upper() for x in SECRET_MARKERS) for key in env):
            raise ValueError(f"forbidden {name} env")
        variants[name] = {"document_root": str(root), "env": dict(env)}
    workloads = raw.get("workloads")
    if not isinstance(workloads, list) or len(workloads) < 2: raise ValueError("at least two workloads required")
    seen, kinds, normalized = set(), set(), []
    for item in workloads:
        name, kind = item.get("name"), item.get("kind")
        path, iterations = item.get("path", "/index.html"), item.get("iterations", 3)
        if not isinstance(name, str) or not name or name in seen: raise ValueError("invalid workload name")
        if kind not in KINDS: raise ValueError("invalid workload kind")
        if not isinstance(path, str) or not path.startswith("/") or "://" in path: raise ValueError("invalid local path")
        if not isinstance(iterations, int) or not 1 <= iterations <= 100: raise ValueError("invalid iterations")
        normalized.append({"name": name, "kind": kind, "path": path, "iterations": iterations})
        seen.add(name); kinds.add(kind)
    if len(kinds) < 2: raise ValueError("two workload kinds required")
    return {"schema": SCHEMA, "warmups": warmups, "samples": samples,
            "baseline": variants["baseline"], "candidate": variants["candidate"], "workloads": normalized}


def clean_env(extra):
    Path("/tmp/lda-e2e-home").mkdir(parents=True, exist_ok=True)
    env = {"PATH": "/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin",
           "HOME": "/tmp/lda-e2e-home", "LANG": "C.UTF-8", "LC_ALL": "C.UTF-8", "TMPDIR": "/tmp"}
    env.update(extra)
    return env


class QuietHandler(http.server.SimpleHTTPRequestHandler):
    def log_message(self, *_): pass


@contextmanager
def server(root):
    handler = lambda *args, **kwargs: QuietHandler(*args, directory=root, **kwargs)
    instance = socketserver.TCPServer(("127.0.0.1", 0), handler, bind_and_activate=True)
    thread = threading.Thread(target=instance.serve_forever, daemon=True); thread.start()
    try: yield f"http://127.0.0.1:{instance.server_address[1]}"
    finally: instance.shutdown(); instance.server_close(); thread.join(timeout=5)


def web_sample(url, iterations, _env):
    start = time.perf_counter_ns()
    for _ in range(iterations):
        with urllib.request.urlopen(url, timeout=10) as response:
            body = response.read()
            if response.status != 200 or b"LDA_E2E_READY" not in body: raise RuntimeError("web verification failed")
    return time.perf_counter_ns() - start


def chrome_binary():
    for name in ("chromium", "chromium-browser", "google-chrome"):
        found = shutil.which(name)
        if found: return found
    try:
        from playwright.sync_api import sync_playwright
        with sync_playwright() as playwright:
            found = playwright.chromium.executable_path
        if found and Path(found).is_file(): return found
    except Exception:
        pass
    raise RuntimeError("Chromium executable not found")


def chrome_sample(url, iterations, env, binary=None):
    binary = binary or chrome_binary(); start = time.perf_counter_ns()
    for index in range(iterations):
        profile = f"/tmp/lda-chrome-{os.getpid()}-{index}"
        command = [binary, "--headless=new", "--disable-gpu", "--no-sandbox", "--disable-dev-shm-usage",
                   "--disable-background-networking", "--disable-component-update", "--disable-sync",
                   "--metrics-recording-only", "--no-first-run", f"--user-data-dir={profile}", "--dump-dom", url]
        command.insert(-2, "--host-resolver-rules=MAP * 0.0.0.0, EXCLUDE 127.0.0.1")
        result = subprocess.run(command, env=clean_env(env), stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                timeout=30, check=False)
        shutil.rmtree(profile, ignore_errors=True)
        if result.returncode != 0 or b"LDA_E2E_READY" not in result.stdout:
            raise RuntimeError("chrome verification failed: " + result.stderr.decode(errors="replace")[-500:])
    return time.perf_counter_ns() - start


def measure(config, workload, browser=None):
    fn = web_sample if workload["kind"] == "web_server" else chrome_sample
    values = {"baseline": [], "candidate": []}
    servers = {}
    with server(config["baseline"]["document_root"]) as base_url, server(config["candidate"]["document_root"]) as cand_url:
        servers.update({"baseline": base_url, "candidate": cand_url})
        for _ in range(config["warmups"]):
            for variant in ("baseline", "candidate"):
                if workload["kind"] == "chrome_gui":
                    fn(servers[variant] + workload["path"], workload["iterations"], config[variant]["env"], browser)
                else:
                    fn(servers[variant] + workload["path"], workload["iterations"], config[variant]["env"])
        for index in range(config["samples"]):
            order = ("baseline", "candidate") if index % 2 == 0 else ("candidate", "baseline")
            for variant in order:
                if workload["kind"] == "chrome_gui":
                    value = fn(servers[variant] + workload["path"], workload["iterations"], config[variant]["env"], browser)
                else:
                    value = fn(servers[variant] + workload["path"], workload["iterations"], config[variant]["env"])
                values[variant].append(value)
    speedup = (sum(values["baseline"]) / len(values["baseline"])) / (sum(values["candidate"]) / len(values["candidate"]))
    return {"kind": workload["kind"], "baseline": values["baseline"], "candidate": values["candidate"],
            "samples": config["samples"], "warmups": config["warmups"], "iterations": workload["iterations"],
            "speedup": speedup}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", default="/workspace/portfolio-e2e.json")
    parser.add_argument("--output", default="/workspace/artifacts/portfolio-e2e.json")
    parser.add_argument("--browser", default=None)
    args = parser.parse_args()
    try:
        config = validate(json.loads(Path(args.config).read_text(encoding="utf-8")))
        digest = hashlib.sha256(json.dumps(config, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
        browser = args.browser or chrome_binary()
        if not Path(browser).is_file(): raise ValueError("browser executable does not exist")
        raw = {item["name"]: measure(config, item, browser) for item in config["workloads"]}
        speeds = {name: item["speedup"] for name, item in raw.items()}
        geomean = math.prod(speeds.values()) ** (1 / len(speeds))
        result = {"schema": SCHEMA, "config_sha256": digest, "workloads": speeds, "raw_workloads": raw,
                  "geomean_speedup": geomean, "improved_workloads": sum(x > 1 for x in speeds.values()),
                  "metadata": {"kernel": platform.release(), "python": platform.python_version(),
                               "browser": browser, "network_scope": "loopback-only"}}
        output = Path(args.output); output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(result, sort_keys=True) + "\n", encoding="utf-8")
        print(json.dumps(result, sort_keys=True))
        return 0
    except Exception as exc:
        print(json.dumps({"schema": SCHEMA, "invalid": True, "reason": str(exc)}, sort_keys=True), file=sys.stderr)
        return 2


if __name__ == "__main__": raise SystemExit(main())
