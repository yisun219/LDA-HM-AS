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

TARGET_CPU_FINGERPRINT = {
    "vendor_id": "GenuineIntel",
    "family": 6,
    "model": 207,
    "stepping": 2,
    "required_flags": frozenset({"avx2", "avx512f", "avx512dq", "avx512bw", "avx512vl",
                                 "avx512_vnni", "amx_tile", "amx_int8", "amx_bf16"}),
}
ALLOWED_OPTIMIZATION_FLAGS = frozenset({
    "-O2", "-O3", "-fno-plt", "-ffunction-sections", "-fdata-sections", "-flto=auto",
})


def validate_optimization_flags(flags: list[str] | tuple[str, ...] | None) -> tuple[str, ...]:
    values = tuple(dict.fromkeys(flags or ("-O3", "-fno-plt")))
    rejected = sorted(value for value in values if value not in ALLOWED_OPTIMIZATION_FLAGS)
    if rejected:
        raise ValueError("unsupported or ABI-risking optimization flags: " + ", ".join(rejected))
    if not any(value in {"-O2", "-O3"} for value in values):
        raise ValueError("an explicit safe optimization level is required")
    return values


def architecture_compatibility(profile: dict[str, Any]) -> dict[str, Any]:
    """Compare architectural capability without claiming physical identity.

    CPUID values in a VM are controlled by the hypervisor. A matching tuple is
    useful for dispatch/benchmark compatibility, but is not hardware attestation.
    """
    flags = set(profile.get("flags", []))
    missing = sorted(TARGET_CPU_FINGERPRINT["required_flags"] - flags)
    tuple_matches = (
        profile.get("vendor_id") == TARGET_CPU_FINGERPRINT["vendor_id"]
        and profile.get("family") == TARGET_CPU_FINGERPRINT["family"]
        and profile.get("model") == TARGET_CPU_FINGERPRINT["model"]
        and profile.get("stepping") == TARGET_CPU_FINGERPRINT["stepping"]
    )
    virtualized = bool(profile.get("hypervisor")) or "hypervisor" in flags
    compatible = tuple_matches and not missing
    # This local observation cannot attest physical identity, even on bare
    # metal. Identity must come from a separately verified control-plane or
    # hardware attestation bound to sandbox_id, lease_id, and a fresh nonce.
    return {"compatible": compatible, "tuple_matches": tuple_matches,
            "missing_flags": missing, "virtualized": virtualized,
            "identity_attested": False}


# This program deliberately does not contain a claimed speedup. It measures the
# installed baseline and candidate libraries in the sandbox and emits raw samples.
HARNESS = r'''#!/usr/bin/env python3
import argparse, ctypes, ctypes.util, http.server, json, os, platform, subprocess, threading, time
from pathlib import Path

def _hardware():
    def read(path):
        try: return Path(path).read_text().strip()
        except OSError: return "unknown"
    fields = {}
    try:
        for line in Path("/proc/cpuinfo").read_text().split("\n\n", 1)[0].splitlines():
            if ":" in line:
                key, value = line.split(":", 1)
                fields[key.strip()] = value.strip()
    except OSError: pass
    flags = fields.get("flags", "").split()
    return {"cpu_model": fields.get("model name", "unknown"),
            "vendor_id": fields.get("vendor_id", "unknown"),
            "family": int(fields.get("cpu family", "-1")),
            "model": int(fields.get("model", "-1")),
            "stepping": int(fields.get("stepping", "-1")),
            "microcode": fields.get("microcode", "unknown"),
            "flags": flags, "hypervisor": "kvm" if "hypervisor" in flags else "",
            "kernel": platform.release(),
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

def _runtime_env(root):
    env = os.environ.copy()
    if root:
        dirs = sorted({str(path.parent) for name in ("libcairo.so.2", "libsoup-3.0.so.0")
                       for path in Path(root).rglob(name)})
        env["LD_LIBRARY_PATH"] = ":".join(dirs + ([env["LD_LIBRARY_PATH"]] if env.get("LD_LIBRARY_PATH") else []))
    return env

def _external_samples(argv, root, warmups, samples):
    env = _runtime_env(root)
    values = []
    for index in range(warmups + samples):
        start = time.perf_counter_ns()
        result = subprocess.run(argv, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
        elapsed = time.perf_counter_ns() - start
        if result.returncode: raise RuntimeError("external workload failed: " + result.stderr.decode(errors="replace")[-500:])
        if index >= warmups: values.append(elapsed)
    return values

def _svg(path, shapes, size):
    body = []
    for i in range(shapes):
        x = (i * 37) % size; y = (i * 53) % size; radius = 3 + (i % 17)
        body.append(f'<circle cx="{x}" cy="{y}" r="{radius}" fill="rgb({i%251},{(i*3)%251},{(i*7)%251})" fill-opacity="0.55"/>')
    path.write_text(f'<svg xmlns="http://www.w3.org/2000/svg" width="{size}" height="{size}"><rect width="100%" height="100%" fill="white"/>{"".join(body)}</svg>')

SOUP_CLIENT = r"""#include <libsoup/soup.h>
#include <stdlib.h>
int main(int argc, char **argv) {
  if (argc != 3) return 64;
  int count = atoi(argv[2]);
  SoupSession *session = soup_session_new();
  for (int i = 0; i < count; i++) {
    GError *error = NULL;
    SoupMessage *message = soup_message_new("GET", argv[1]);
    GBytes *body = soup_session_send_and_read(session, message, NULL, &error);
    if (error || !body || g_bytes_get_size(body) == 0) return 65;
    g_bytes_unref(body); g_object_unref(message);
  }
  g_object_unref(session); return 0;
}"""

def _soup_client(out):
    source = out / "soup_e2e_client.c"; binary = out / "soup_e2e_client"
    source.write_text(SOUP_CLIENT)
    flags = subprocess.check_output(["pkg-config", "--cflags", "--libs", "libsoup-3.0"], text=True).split()
    subprocess.run(["cc", "-O2", str(source), "-o", str(binary), *flags], check=True)
    return binary

class _Handler(http.server.BaseHTTPRequestHandler):
    payload = (b"lda-e2e-payload-" * 1024)
    def do_GET(self):
        self.send_response(200); self.send_header("Content-Length", str(len(self.payload)))
        self.end_headers(); self.wfile.write(self.payload)
    def log_message(self, *_): pass

def _e2e(package, out, baseline_root, candidate_root, warmups, samples):
    workloads = {}
    if package == "libcairo2":
        for name, size, shapes in (("rsvg_medium", 384, 350), ("rsvg_large", 1024, 1400)):
            source = out / (name + ".svg"); _svg(source, shapes, size)
            argv = ["rsvg-convert", "-w", str(size), "-h", str(size), str(source), "-o", "/dev/null"]
            workloads[name] = {"baseline": _external_samples(argv, baseline_root, warmups, samples),
                               "candidate": _external_samples(argv, candidate_root, warmups, samples)}
        return workloads, "unchanged_prebuilt_rsvg_convert"
    binary = _soup_client(out)
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True); thread.start()
    try:
        url = f"http://127.0.0.1:{server.server_port}/payload"
        for name, requests in (("http_small", 20), ("http_large", 100)):
            argv = [str(binary), url, str(requests)]
            workloads[name] = {"baseline": _external_samples(argv, baseline_root, warmups, samples),
                               "candidate": _external_samples(argv, candidate_root, warmups, samples)}
    finally:
        server.shutdown(); server.server_close(); thread.join(timeout=5)
    return workloads, "precompiled_c_client_local_http_server"

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
    # End-to-end evidence crosses an unchanged application/process boundary.
    e2e, e2e_kind = _e2e(args.package, out, "", args.candidate_root,
                         max(2, args.warmups // 2), max(10, args.samples // 2))
    metadata = _hardware()
    metadata["package"] = args.package; metadata["loops"] = loops
    (out / "micro.json").write_text(json.dumps({"schema": "lda.micro.v1", "package": args.package,
        "baseline": baseline, "candidate": candidate, "warmups": args.warmups,
        "samples": args.samples, "hardware": metadata}, sort_keys=True) + "\n")
    (out / "e2e.json").write_text(json.dumps({"schema": "lda.e2e.v1", "package": args.package,
        "workloads": e2e, "workload_kind": e2e_kind, "hardware": metadata}, sort_keys=True) + "\n")
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
                      build_root: str = "/workspace/candidate-build", *,
                      cflags: list[str] | tuple[str, ...] | None = None,
                      cxxflags: list[str] | tuple[str, ...] | None = None) -> str:
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
        safe_cflags = " ".join(validate_optimization_flags(cflags))
        safe_cxxflags = " ".join(validate_optimization_flags(cxxflags or cflags))
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
            f"cd {shlex.quote(build_root + '/src')} && DEB_CFLAGS_MAINT_APPEND={shlex.quote(safe_cflags)} DEB_CXXFLAGS_MAINT_APPEND={shlex.quote(safe_cxxflags)} dpkg-buildpackage -us -uc -b -d > /workspace/candidate-build.log 2>&1",
            f"tail -n 120 /workspace/candidate-build.log; find {shlex.quote(build_root)} -maxdepth 1 -type f -name '*.deb' -print",
        ))

    def build_candidate(self, sandbox: Sandbox, package: str, *, source_root: str = "/workspace/source-snapshot/20260825T000000Z",
                        build_root: str = "/workspace/candidate-build",
                        cflags: list[str] | tuple[str, ...] | None = None,
                        cxxflags: list[str] | tuple[str, ...] | None = None) -> dict[str, Any]:
        """Build a canary candidate and return only observed artifact evidence."""
        command = self.build_command(package, source_root, build_root, cflags=cflags, cxxflags=cxxflags)
        result = self.client.command_checkpointed(sandbox, command, timeout=1800)
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
        benchmark_packages = ([package, "librsvg2-bin"] if package == "libcairo2"
                              else [package, "libsoup-3.0-dev", "gcc", "pkg-config"])
        query = " ".join(shlex.quote(item) for item in benchmark_packages)
        available = self.client.command(sandbox, f"dpkg-query -W -f='${{Status}}\\n' {query}")
        if available.get("exit_code") != 0 or (available.get("stdout") or "").count("install ok installed") != len(benchmark_packages):
            installed = self.client.command_checkpointed(
                sandbox, f"apt-get install -y --no-install-recommends {query}", timeout=600)
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
            compatibility = architecture_compatibility(hardware)
            # The benchmark fence is architectural: exact CPUID tuple plus the
            # required dispatch ISA. Physical host identity remains separately
            # reported as unattested under KVM and must never be inferred from
            # the generic guest brand or masked microcode.
            hardware_valid = compatibility["compatible"]
            blockers = []
            warnings = []
            if not compatibility["compatible"]:
                blockers.append("hardware_architecture_mismatch")
            if compatibility["virtualized"]:
                warnings.append("hardware_identity_unattested:kvm_cpuid_is_hypervisor_controlled")
            elif not compatibility["identity_attested"]:
                warnings.append("hardware_identity_unattested")
            return {"invalid": False, "accepted": bool(measured.get("accepted") and not portfolio["invalid"] and hardware_valid),
                    "package_metadata": (package_metadata.get("stdout") or "").strip(),
                    "micro_speedup": measured["speedup"], "micro_ci_lower": measured["ci_lower"],
                    "e2e_speedup": portfolio["geomean_speedup"], "improved_workloads": portfolio["improved_workloads"],
                    "micro": measured, "portfolio": portfolio,
                    "e2e_workload_kind": e2e_raw.get("workload_kind", "unknown"),
                    "hardware": hardware, "hardware_compatibility": compatibility,
                    "hardware_valid": hardware_valid,
                    "acceptance_blockers": blockers,
                    "acceptance_warnings": warnings,
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
