from __future__ import annotations

import hashlib
import json
import os
import shlex
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from lda.benchmarks.runner import BenchmarkConfig, BenchmarkRunner
from lda.e2b.client import E2BClient, Sandbox


CANARY_PACKAGES = ("libcairo2", "libsoup-3.0-0")


@dataclass(frozen=True)
class CanarySpec:
    package: str
    source_package: str
    library_names: tuple[str, ...]


SPECS = {
    "libcairo2": CanarySpec("libcairo2", "cairo", ("libcairo.so.2",)),
    "libsoup-3.0-0": CanarySpec("libsoup-3.0-0", "libsoup3", ("libsoup-3.0.so.0",)),
}


# This program deliberately does not contain a claimed speedup. It measures the
# installed baseline and candidate libraries in the sandbox and emits raw samples.
HARNESS = r'''#!/usr/bin/env python3
import argparse, ctypes, ctypes.util, json, os, platform, subprocess, time
from pathlib import Path

def _hardware():
    def read(path):
        try: return Path(path).read_text().strip()
        except OSError: return "unknown"
    cpu = "unknown"
    try:
        for line in Path("/proc/cpuinfo").read_text().splitlines():
            if line.lower().startswith("model name"):
                cpu = line.split(":", 1)[1].strip(); break
    except OSError: pass
    return {"cpu_model": cpu, "kernel": platform.release(),
            "governor": read("/sys/devices/system/cpu/cpu0/cpufreq/scaling_governor"),
            "turbo": read("/sys/devices/system/cpu/intel_pstate/no_turbo"),
            "numa": read("/sys/devices/system/node/online"),
            "python": platform.python_version()}

def _lib(name, root):
    if root:
        for base in (Path(root) / "usr/lib", Path(root) / "lib", Path(root)):
            if base.exists():
                hits = list(base.rglob(name))
                if hits: return ctypes.CDLL(str(hits[0]), mode=ctypes.RTLD_LOCAL)
    lookup = name[3:].split(".so", 1)[0] if name.startswith("lib") else name
    found = ctypes.util.find_library(lookup)
    if not found: raise RuntimeError("library not found: " + name)
    return ctypes.CDLL(found, mode=ctypes.RTLD_LOCAL)

def _cairo(root, loops):
    lib = _lib("libcairo.so.2", root)
    ptr = ctypes.c_void_p
    lib.cairo_image_surface_create.argtypes = [ctypes.c_int, ctypes.c_int, ctypes.c_int]
    lib.cairo_image_surface_create.restype = ptr
    lib.cairo_create.argtypes = [ptr]; lib.cairo_create.restype = ptr
    lib.cairo_set_source_rgba.argtypes = [ptr, ctypes.c_double, ctypes.c_double, ctypes.c_double, ctypes.c_double]
    lib.cairo_paint.argtypes = [ptr]
    lib.cairo_destroy.argtypes = [ptr]
    lib.cairo_surface_destroy.argtypes = [ptr]
    start = time.perf_counter_ns()
    for i in range(loops):
        surface = lib.cairo_image_surface_create(0, 128 + (i & 7), 128 + (i & 7))
        context = lib.cairo_create(surface)
        lib.cairo_set_source_rgba(context, 0.13, 0.27, 0.41, 1.0)
        lib.cairo_paint(context)
        lib.cairo_destroy(context); lib.cairo_surface_destroy(surface)
    return time.perf_counter_ns() - start

def _soup(root, loops):
    soup = _lib("libsoup-3.0.so.0", root)
    glib = ctypes.CDLL(ctypes.util.find_library("gobject-2.0") or "libgobject-2.0.so.0")
    soup.soup_message_new.argtypes = [ctypes.c_char_p, ctypes.c_char_p]
    soup.soup_message_new.restype = ctypes.c_void_p
    glib.g_object_unref.argtypes = [ctypes.c_void_p]
    start = time.perf_counter_ns()
    for i in range(loops):
        msg = soup.soup_message_new(b"GET", (b"http://127.0.0.1/%d" % (i & 31)))
        if not msg: raise RuntimeError("soup_message_new returned null")
        glib.g_object_unref(msg)
    return time.perf_counter_ns() - start

def _measure(package, root, loops, warmups, samples):
    fn = _cairo if package == "libcairo2" else _soup
    for _ in range(warmups): fn(root, loops)
    return [fn(root, loops) for _ in range(samples)]

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--package", required=True, choices=["libcairo2", "libsoup-3.0-0"])
    ap.add_argument("--out", required=True)
    ap.add_argument("--candidate-root", default="")
    ap.add_argument("--warmups", type=int, default=10)
    ap.add_argument("--samples", type=int, default=30)
    args = ap.parse_args()
    if args.warmups < 0 or args.samples < 2: raise SystemExit("invalid sample configuration")
    out = Path(args.out); out.mkdir(parents=True, exist_ok=True)
    loops = (250 if args.package == "libsoup-3.0-0" else 120)
    baseline = _measure(args.package, "", loops, args.warmups, args.samples)
    candidate = _measure(args.package, args.candidate_root, loops, args.warmups, args.samples)
    # Two independent end-to-end guardrail workloads with different sizes.
    e2e = {}
    for name, size in (("small", max(20, loops // 4)), ("large", loops * 2)):
        b = _measure(args.package, "", size, max(1, args.warmups // 2), max(5, args.samples // 2))
        c = _measure(args.package, args.candidate_root, size, max(1, args.warmups // 2), max(5, args.samples // 2))
        e2e[name] = {"baseline": b, "candidate": c}
    metadata = _hardware()
    metadata["package"] = args.package; metadata["loops"] = loops
    (out / "micro.json").write_text(json.dumps({"schema": "lda.micro.v1", "package": args.package,
        "baseline": baseline, "candidate": candidate, "warmups": args.warmups,
        "samples": args.samples, "hardware": metadata}, sort_keys=True) + "\n")
    (out / "e2e.json").write_text(json.dumps({"schema": "lda.e2e.v1", "package": args.package,
        "workloads": e2e, "hardware": metadata}, sort_keys=True) + "\n")
    print(json.dumps({"package": args.package, "micro": str(out / "micro.json"),
                      "e2e": str(out / "e2e.json"), "hardware": metadata}, sort_keys=True))

if __name__ == "__main__": main()
'''


class CanaryBenchmarkRunner:
    """Upload and execute the deterministic canary harness inside E2B."""

    def __init__(self, client: E2BClient, config: BenchmarkConfig | None = None):
        self.client = client
        self.config = config or BenchmarkConfig()

    @staticmethod
    def validate_package(package: str) -> CanarySpec:
        try:
            return SPECS[package]
        except KeyError as exc:
            raise ValueError(f"unsupported canary package: {package}") from exc

    def install(self, sandbox: Sandbox) -> str:
        path = "/workspace/benchmarks/lda_canary_harness.py"
        self.client.filesystem_write(sandbox, path, HARNESS)
        digest = hashlib.sha256(HARNESS.encode()).hexdigest()
        check = self.client.command(sandbox, f"sha256sum {shlex.quote(path)}")
        if check.get("exit_code") != 0 or digest not in (check.get("stdout") or ""):
            raise RuntimeError("canary harness hash verification failed in E2B")
        return path

    def command(self, package: str, harness_path: str, *, candidate_root: str = "") -> str:
        self.validate_package(package)
        args = ["python3", harness_path, "--package", package, "--out", "/workspace/benchmarks"]
        if candidate_root:
            args.extend(["--candidate-root", candidate_root])
        args.extend(["--warmups", str(self.config.warmups), "--samples", str(self.config.samples)])
        return " ".join(shlex.quote(x) for x in args)

    def build_command(self, package: str, source_root: str = "/workspace/source-snapshot/20260825T000000Z",
                      build_root: str = "/workspace/candidate-build") -> str:
        """Return a bounded source-build command for a pinned canary bundle.

        The command produces a separate staging tree and package artifacts. It
        never mutates the official package installation; callers decide whether
        to install a resulting .deb in a disposable sandbox.
        """
        spec = self.validate_package(package)
        dsc = {
            "libcairo2": f"{source_root}/cairo/cairo_1.18.4-3.dsc",
            "libsoup-3.0-0": f"{source_root}/libsoup3/libsoup3_3.6.6-1.dsc",
        }[spec.package]
        # Build dependencies are installed only in the disposable candidate
        # sandbox. The source tarballs themselves remain pinned to the uploaded
        # SHA-256-verified snapshot.
        source_base = os.environ.get("LDA_BUILD_SOURCES_BASE", "https://snapshot.ubuntu.com/ubuntu/20260825T000000Z")
        source_lines = "\n".join((
            f"deb {source_base} resolute main universe multiverse restricted",
            f"deb-src {source_base} resolute main universe multiverse restricted",
            f"deb {source_base} resolute-updates main universe multiverse restricted",
            f"deb-src {source_base} resolute-updates main universe multiverse restricted",
            f"deb {source_base} resolute-security main universe multiverse restricted",
            f"deb-src {source_base} resolute-security main universe multiverse restricted",
        ))
        source_dir = f"{source_root}/{'cairo' if package == 'libcairo2' else 'libsoup3'}"
        source_name = spec.source_package
        source_version = "1.18.4-3" if package == "libcairo2" else "3.6.6-1"
        source_prefix = "cairo" if package == "libcairo2" else "libsoup3"
        return " && ".join((
            f"printf '%s\\n' {shlex.quote(source_lines)} > /etc/apt/sources.list.d/lda-build-deps.list",
            "DEBIAN_FRONTEND=noninteractive apt-get update > /workspace/candidate-build-apt-update.log 2>&1",
            f"DEBIAN_FRONTEND=noninteractive apt-get -o Dir::Etc::sourcelist=/etc/apt/sources.list.d/lda-build-deps.list -o Dir::Etc::sourceparts=- -o APT::Get::Assume-Yes=true build-dep {shlex.quote(spec.source_package)} > /workspace/candidate-build-deps.log 2>&1",
            # Candidate sandboxes fetch the exact pinned source from the fixed
            # snapshot, then verify the uploaded manifest hashes.  This avoids
            # repeatedly sending 33 MB tarballs through the gateway filesystem
            # RPC while preserving source identity and fail-closed behavior.
            f"mkdir -p {shlex.quote(source_dir)} && if [ ! -f {shlex.quote(source_dir + '/' + source_prefix + '_' + source_version + '.dsc')} ]; then cd {shlex.quote(source_dir)} && apt-get -o Dir::Etc::sourcelist=/etc/apt/sources.list.d/lda-build-deps.list -o Dir::Etc::sourceparts=- source --download-only {shlex.quote(source_name + '=' + source_version)} > /workspace/candidate-source-fetch.log 2>&1; fi",
            f"cd {shlex.quote(source_root)} && grep '  {source_prefix}/' SHA256SUMS > {source_prefix}.SHA256SUMS && (cd {shlex.quote(source_prefix)} && sha256sum -c ../{source_prefix}.SHA256SUMS)",
            f"rm -rf {shlex.quote(build_root)}",
            f"mkdir -p {shlex.quote(build_root)}",
            f"dpkg-source -x {shlex.quote(dsc)} {shlex.quote(build_root + '/src')}",
            f"cd {shlex.quote(build_root + '/src')} && DEB_CFLAGS_MAINT_APPEND='-O3 -fno-plt' DEB_CXXFLAGS_MAINT_APPEND='-O3 -fno-plt' dpkg-buildpackage -us -uc -b -d > /workspace/candidate-build.log 2>&1",
            f"tail -n 120 /workspace/candidate-build.log; find {shlex.quote(build_root)} -maxdepth 1 -type f -name '*.deb' -print",
        ))

    def build_candidate(self, sandbox: Sandbox, package: str, *, source_root: str = "/workspace/source-snapshot/20260825T000000Z",
                        build_root: str = "/workspace/candidate-build") -> dict[str, Any]:
        """Build a canary candidate and return only observed artifact evidence."""
        command = self.build_command(package, source_root, build_root)
        result = self.client.command(sandbox, command, timeout=1800)
        if result.get("exit_code") != 0:
            return {"passed": False, "command": command, "exit_code": result.get("exit_code"),
                    "stderr": result.get("stderr", ""), "artifacts": []}
        listing = result.get("stdout", "")
        artifacts = [line.strip() for line in listing.splitlines() if line.strip().endswith(".deb")]
        if not artifacts:
            return {"passed": False, "command": command, "exit_code": result.get("exit_code"),
                    "reason": "build_succeeded_without_deb_artifact", "artifacts": []}
        target = next((item for item in artifacts if Path(item).name.startswith(package + "_")), None)
        artifact_hash = None
        if target:
            hashed = self.client.command(sandbox, f"sha256sum {shlex.quote(target)}")
            if hashed.get("exit_code") == 0:
                artifact_hash = (hashed.get("stdout") or "").split()[0]
        return {"passed": bool(target), "command": command, "exit_code": result.get("exit_code"),
                "artifacts": artifacts, "target_artifact": target, "target_sha256": artifact_hash,
                "reason": None if target else "target_binary_deb_missing"}

    def run(self, sandbox: Sandbox, package: str, *, candidate_root: str = "") -> dict[str, Any]:
        harness = self.install(sandbox)
        self.validate_package(package)
        # The base template intentionally contains toolchains, not target
        # packages. Install the pinned runtime from the sandbox apt snapshot
        # before measuring; failure is reported as invalid evidence.
        available = self.client.command(sandbox, f"dpkg-query -W -f='${{Status}}' {shlex.quote(package)}")
        if available.get("exit_code") != 0 or "install ok installed" not in (available.get("stdout") or ""):
            installed = self.client.command(sandbox, f"apt-get install -y --no-install-recommends {shlex.quote(package)}")
            if installed.get("exit_code") != 0:
                return {"invalid": True, "reason": "canary_runtime_install_failed",
                        "stderr": installed.get("stderr", ""), "micro_speedup": 0.0,
                        "micro_ci_lower": 0.0, "e2e_speedup": 0.0, "improved_workloads": 0,
                        "evidence_refs": []}
        package_metadata = self.client.command(
            sandbox, f"dpkg-query -W -f='${{Package}} ${{Version}} ${{Architecture}}\\n' {shlex.quote(package)}"
        )
        result = self.client.command(sandbox, self.command(package, harness, candidate_root=candidate_root))
        if result.get("exit_code") != 0:
            return {"invalid": True, "reason": "canary_harness_failed", "command": result.get("command"),
                    "stderr": result.get("stderr", ""), "micro_speedup": 0.0,
                    "micro_ci_lower": 0.0, "e2e_speedup": 0.0, "improved_workloads": 0,
                    "evidence_refs": []}
        try:
            micro = json.loads(self.client.filesystem_read(sandbox, "/workspace/benchmarks/micro.json"))
            e2e_raw = json.loads(self.client.filesystem_read(sandbox, "/workspace/benchmarks/e2e.json"))
            if micro.get("package") != package or e2e_raw.get("package") != package:
                raise ValueError("benchmark package mismatch")
            measured = BenchmarkRunner(self.config).measure(micro["baseline"], micro["candidate"], kind="micro")
            workloads = {}
            for name, pair in e2e_raw["workloads"].items():
                item = BenchmarkRunner(self.config).measure(pair["baseline"], pair["candidate"], kind="e2e")
                if item.get("invalid"): raise ValueError(f"invalid E2E workload: {name}")
                workloads[name] = item["speedup"]
            portfolio = BenchmarkRunner(self.config).portfolio(workloads)
            hardware = micro.get("hardware", {})
            target_pattern = os.environ.get("LDA_TARGET_CPU_PATTERN", "6548Y")
            hardware_valid = target_pattern.lower() in str(hardware.get("cpu_model", "")).lower()
            blockers = [] if hardware_valid else [f"hardware_cpu_mismatch:{hardware.get('cpu_model', 'unknown')}:{target_pattern}"]
            return {"invalid": False, "accepted": bool(measured.get("accepted") and not portfolio["invalid"] and hardware_valid),
                    "package_metadata": (package_metadata.get("stdout") or "").strip(),
                    "micro_speedup": measured["speedup"], "micro_ci_lower": measured["ci_lower"],
                    "e2e_speedup": portfolio["geomean_speedup"], "improved_workloads": portfolio["improved_workloads"],
                    "micro": measured, "portfolio": portfolio,
                    "hardware": hardware, "hardware_valid": hardware_valid,
                    "acceptance_blockers": blockers,
                    "evidence_refs": ["/workspace/benchmarks/micro.json", "/workspace/benchmarks/e2e.json"]}
        except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
            return {"invalid": True, "accepted": False, "reason": f"invalid_canary_evidence: {exc}",
                    "micro_speedup": 0.0, "micro_ci_lower": 0.0, "e2e_speedup": 0.0,
                    "improved_workloads": 0, "evidence_refs": []}


def upload_source_snapshot(client: E2BClient, sandbox: Sandbox, source_root: str | Path,
                           snapshot: str = "20260825T000000Z", *, include_payload: bool = True) -> dict[str, Any]:
    """Upload and verify every file in a pinned source snapshot manifest."""
    root = Path(source_root).resolve() / snapshot
    manifest = root / "SHA256SUMS"
    if not manifest.is_file():
        raise FileNotFoundError(manifest)
    refs = []
    manifest_target = f"/workspace/source-snapshot/{snapshot}/SHA256SUMS"
    directories = sorted({f"/workspace/source-snapshot/{snapshot}/{Path(line.split('  ', 1)[1]).parent}"
                         for line in manifest.read_text(encoding="utf-8").splitlines() if line.strip()})
    if directories:
        client.command(sandbox, "mkdir -p " + " ".join(shlex.quote(item) for item in directories))
    client.filesystem_write(sandbox, manifest_target, manifest.read_bytes())
    refs.append({"path": manifest_target,
                 "sha256": hashlib.sha256(manifest.read_bytes()).hexdigest()})
    for line in manifest.read_text(encoding="utf-8").splitlines():
        digest, relative = line.split("  ", 1)
        path = root / relative
        data = path.read_bytes()
        if hashlib.sha256(data).hexdigest() != digest:
            raise ValueError(f"source snapshot hash mismatch: {path}")
        if not include_payload:
            continue
        target = f"/workspace/source-snapshot/{snapshot}/{relative}"
        client.filesystem_write(sandbox, target, data)
        refs.append({"path": target, "sha256": digest})
    if include_payload:
        check = client.command(sandbox, f"cd /workspace/source-snapshot/{snapshot} && sha256sum -c SHA256SUMS")
        if check.get("exit_code") != 0:
            raise RuntimeError("E2B source snapshot verification failed")
    return {"snapshot": snapshot, "manifest_sha256": hashlib.sha256(manifest.read_bytes()).hexdigest(), "files": refs}


__all__ = ["CANARY_PACKAGES", "CanaryBenchmarkRunner", "CanarySpec", "SPECS", "upload_source_snapshot"]
