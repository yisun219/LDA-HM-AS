"""Offline deterministic Judge for canary binary packages."""

from __future__ import annotations

import hashlib
import json
import shlex
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from lda.e2b.client import E2BClient, Sandbox


@dataclass(frozen=True)
class CanaryJudgeSpec:
    package: str
    dev_package: str
    library: str
    smoke_symbol: str


SPECS = {
    "libcairo2": CanaryJudgeSpec("libcairo2", "libcairo2-dev", "libcairo.so.2", "cairo_version"),
    "libsoup-3.0-0": CanaryJudgeSpec("libsoup-3.0-0", "libsoup-3.0-dev", "libsoup-3.0.so.0", "soup_get_major_version"),
}
JUDGE_TEMPLATE = "lda-judge-v4-20260826"


# The script runs inside lda-judge. It has no network, model runtime, or
# credentials. All comparisons are derived from the four uploaded runtime/dev
# package files (official baseline and candidate).
JUDGE_SCRIPT = r'''#!/usr/bin/env python3
import ctypes, hashlib, json, os, platform, re, subprocess, sys
from pathlib import Path

package, dev_package, official_deb, official_dev_deb, candidate_deb, candidate_dev_deb, library_name, smoke_symbol, output = sys.argv[1:]

def run(argv):
    p = subprocess.run(argv, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    return {"exit_code": p.returncode, "stdout": p.stdout, "stderr": p.stderr}

def sha(path):
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for block in iter(lambda: fh.read(1024 * 1024), b""): h.update(block)
    return h.hexdigest()

def evidence(result):
    return {"exit_code": result["exit_code"],
            "stdout_sha256": hashlib.sha256(result["stdout"].encode()).hexdigest(),
            "stderr_sha256": hashlib.sha256(result["stderr"].encode()).hexdigest()}

def field(deb, name):
    result = run(["dpkg-deb", "-f", deb, name])
    return result["stdout"].strip() if result["exit_code"] == 0 else ""

def extract(deb, root, control):
    Path(root).mkdir(parents=True, exist_ok=True)
    Path(control).mkdir(parents=True, exist_ok=True)
    data = run(["dpkg-deb", "-x", deb, root])
    meta = run(["dpkg-deb", "-e", deb, control])
    return data, meta

def file_manifest(root):
    values = []
    for path in sorted(Path(root).rglob("*")):
        if path.is_file() or path.is_symlink():
            rel = "/" + str(path.relative_to(root))
            values.append({"path": rel, "type": "symlink" if path.is_symlink() else "file",
                           "target": os.readlink(path) if path.is_symlink() else ""})
    return values

def control_manifest(root):
    values = {}
    for path in sorted(Path(root).rglob("*")):
        # Package payload checks cover md5sums. Anti-cheat compares executable
        # maintainer hooks, triggers, and conffile declarations only.
        if path.is_file() and path.name in {"preinst", "postinst", "prerm", "postrm", "triggers", "conffiles"}:
            values[str(path.relative_to(root))] = sha(path)
    return values

def header_manifest(root):
    values = {}
    include = Path(root) / "usr/include"
    if include.exists():
        for path in sorted(include.rglob("*")):
            if path.is_file(): values["/" + str(path.relative_to(root))] = sha(path)
    return values

def library_path(root):
    matches = sorted(p for p in Path(root).rglob(library_name) if p.is_file() or p.is_symlink())
    if not matches: return None
    path = matches[0]
    return str(path.resolve()) if path.is_symlink() else str(path)

def elf_facts(path):
    dynamic = run(["readelf", "-dW", path])
    symbols = run(["readelf", "--dyn-syms", "--wide", path])
    soname = re.findall(r"\(SONAME\).*\[(.*?)\]", dynamic["stdout"])
    needed = sorted(re.findall(r"\(NEEDED\).*\[(.*?)\]", dynamic["stdout"]))
    exports, versions = set(), set()
    for line in symbols["stdout"].splitlines():
        columns = line.split()
        if len(columns) < 8 or columns[6] == "UND": continue
        name = columns[7]
        exports.add(name.split("@", 1)[0])
        if "@" in name: versions.add(name.rsplit("@", 1)[1])
    return {"soname": soname[0] if soname else "", "needed": needed,
            "exports": sorted(exports), "symbol_versions": sorted(versions),
            "commands": {"dynamic": evidence(dynamic), "symbols": evidence(symbols)}}

def pkg_config(root):
    records = {}
    for path in sorted(Path(root).rglob("*.pc")):
        rel = "/" + str(path.relative_to(root))
        fields = {}
        for line in path.read_text(errors="replace").splitlines():
            if ":" in line and line.split(":", 1)[0] in {"Name", "Version", "Libs", "Cflags", "Requires", "Requires.private"}:
                key, value = line.split(":", 1); fields[key] = value.strip()
        records[rel] = fields
    return records

roots = {"official": "/workspace/judge/official-root", "candidate": "/workspace/judge/candidate-root"}
controls = {kind: {part: f"/workspace/judge/{kind}-{part}-control" for part in ("runtime", "dev")} for kind in ("official", "candidate")}
unpack = {}
deb_sets = {"official": {"runtime": official_deb, "dev": official_dev_deb},
            "candidate": {"runtime": candidate_deb, "dev": candidate_dev_deb}}
for kind, debs in deb_sets.items():
    unpack[kind] = {}
    for part, deb in debs.items():
        data, meta = extract(deb, roots[kind], controls[kind][part])
        unpack[kind][part] = {"data": evidence(data), "control": evidence(meta)}

metadata = {kind: {part: {name.lower(): field(deb, name) for name in ("Package", "Version", "Architecture")}
                   for part, deb in debs.items()} for kind, debs in deb_sets.items()}
paths = {kind: file_manifest(root) for kind, root in roots.items()}
control = {kind: {part: control_manifest(root) for part, root in parts.items()} for kind, parts in controls.items()}
libraries = {kind: library_path(root) for kind, root in roots.items()}
elf = {kind: elf_facts(path) if path else {} for kind, path in libraries.items()}
pc = {kind: pkg_config(root) for kind, root in roots.items()}
headers = {kind: header_manifest(root) for kind, root in roots.items()}

checks = {
    "unpack": all(item[stage]["exit_code"] == 0 for kind in unpack.values() for item in kind.values() for stage in ("data", "control")),
    "package": metadata["official"]["runtime"]["package"] == package == metadata["candidate"]["runtime"]["package"] and metadata["official"]["dev"]["package"] == dev_package == metadata["candidate"]["dev"]["package"],
    "version": all(bool(metadata["official"][part]["version"]) and metadata["official"][part]["version"] == metadata["candidate"][part]["version"] for part in ("runtime", "dev")),
    "architecture": all(bool(metadata["official"][part]["architecture"]) and metadata["official"][part]["architecture"] == metadata["candidate"][part]["architecture"] for part in ("runtime", "dev")),
    "install_paths": paths["official"] == paths["candidate"],
    "control_files": control["official"] == control["candidate"],
    "soname": bool(elf["official"].get("soname")) and elf["official"].get("soname") == elf["candidate"].get("soname"),
    "exported_symbols": bool(elf["official"].get("exports")) and elf["official"].get("exports") == elf["candidate"].get("exports"),
    "symbol_versions": elf["official"].get("symbol_versions") == elf["candidate"].get("symbol_versions"),
    "needed": elf["official"].get("needed") == elf["candidate"].get("needed"),
    "headers": bool(headers["official"]) and headers["official"] == headers["candidate"],
    "pkg_config": bool(pc["official"]) and pc["official"] == pc["candidate"],
}

official_install = run(["dpkg", "-i", official_deb, official_dev_deb])
candidate_install = run(["dpkg", "-i", candidate_deb, candidate_dev_deb]) if official_install["exit_code"] == 0 else {"exit_code": 125, "stdout": "", "stderr": "official install failed"}
probe = run(["/opt/lda/judge/ffi_smoke", library_name, smoke_symbol]) if candidate_install["exit_code"] == 0 else {"exit_code": 125, "stdout": "", "stderr": "candidate install failed"}
try:
    lib = ctypes.CDLL(library_name); getattr(lib, smoke_symbol)
    ctypes_ok, ctypes_error = True, ""
except Exception as exc:
    ctypes_ok, ctypes_error = False, str(exc)
rollback = run(["dpkg", "-i", official_deb, official_dev_deb])
installed = run(["dpkg-query", "-W", "-f=${Package} ${Version} ${Architecture}\n", package, dev_package])
checks.update({"package_install": candidate_install["exit_code"] == 0,
               "precompiled_binary": probe["exit_code"] == 0,
               "dlopen_dlsym": probe["exit_code"] == 0,
               "python_ctypes": ctypes_ok,
               "rollback": rollback["exit_code"] == 0 and all(metadata["official"][part]["version"] in installed["stdout"] for part in ("runtime", "dev"))})

secret_names = sorted(name for name in os.environ if name in {"E2B_API_KEY", "E2B_ACCESS_TOKEN", "OPENAI_API_KEY", "CODEX_API_KEY", "OPENAI_BASE_URL"})
ld_preload = os.environ.get("LD_PRELOAD", "")
route = Path("/proc/net/route").read_text(errors="replace") if Path("/proc/net/route").exists() else ""
environment = {"kernel": platform.release(), "machine": platform.machine(),
               "secret_env_names": secret_names, "ld_preload": bool(ld_preload),
               "network_route_sha256": hashlib.sha256(route.encode()).hexdigest(),
               "probe_sha256": sha("/opt/lda/judge/ffi_smoke") if Path("/opt/lda/judge/ffi_smoke").is_file() else "",
               "judge_script_sha256": sha(__file__)}
anti_cheat = {"secret_exposure": bool(secret_names), "ld_preload": bool(ld_preload),
              "control_files_changed": not checks["control_files"],
              "untracked_binary": not checks["install_paths"]}
passed = all(checks.values()) and not any(anti_cheat.values())
payload = {"schema": "lda.canary-judge.v1", "package": package, "valid": passed,
           "checks": checks, "metadata": metadata, "paths": paths, "elf": elf,
           "headers": headers, "pkg_config": pc, "sha256": {"official_deb": sha(official_deb), "official_dev_deb": sha(official_dev_deb),
                                         "candidate_deb": sha(candidate_deb), "candidate_dev_deb": sha(candidate_dev_deb)},
           "install": {"official": evidence(official_install), "candidate": evidence(candidate_install),
                       "precompiled_probe": evidence(probe), "rollback": evidence(rollback),
                       "installed_after_rollback": evidence(installed), "ctypes_error_sha256": hashlib.sha256(ctypes_error.encode()).hexdigest()},
           "unpack": unpack, "environment": environment, "anti_cheat": anti_cheat}
Path(output).write_text(json.dumps(payload, sort_keys=True) + "\n")
print(json.dumps({"valid": passed, "output": output}, sort_keys=True))
sys.exit(0 if passed else 1)
'''


class CleanCanaryJudge:
    """Run the immutable canary Judge in a fresh, offline E2B sandbox."""

    REQUIRED_CHECKS = frozenset({
        "unpack", "package", "version", "architecture", "install_paths", "control_files",
        "soname", "exported_symbols", "symbol_versions", "needed", "headers", "pkg_config",
        "package_install", "precompiled_binary", "dlopen_dlsym", "python_ctypes", "rollback",
    })

    def __init__(self, client: E2BClient):
        self.client = client

    def download_official(self, work: Sandbox, package: str, candidate_debs: dict[str, str]) -> dict[str, Any]:
        spec = SPECS.get(package)
        if spec is None:
            raise ValueError(f"unsupported canary package: {package}")
        if set(candidate_debs) != {"runtime", "dev"} or not all(candidate_debs.values()):
            return {"passed": False, "reason": "runtime_and_dev_candidate_debs_required", "paths": {}}
        command = " && ".join((
            "rm -rf /workspace/judge-official && mkdir -p /workspace/judge-official",
            f"runtime_version=$(dpkg-deb -f {shlex.quote(candidate_debs['runtime'])} Version)",
            f"dev_version=$(dpkg-deb -f {shlex.quote(candidate_debs['dev'])} Version)",
            f"cd /workspace/judge-official && apt-get download {shlex.quote(package)}=\"$runtime_version\" {shlex.quote(spec.dev_package)}=\"$dev_version\"",
            "find /workspace/judge-official -maxdepth 1 -type f -name '*.deb' -print",
        ))
        result = self.client.command_checkpointed(work, command, timeout=600)
        paths = [line.strip() for line in (result.get("stdout") or "").splitlines() if line.strip().endswith(".deb")]
        runtime_path = next((path for path in paths if Path(path).name.startswith(package + "_")), "")
        dev_path = next((path for path in paths if Path(path).name.startswith(spec.dev_package + "_")), "")
        return {"passed": result.get("exit_code") == 0 and bool(runtime_path and dev_path),
                "paths": {"runtime": runtime_path, "dev": dev_path},
                "exit_code": result.get("exit_code"), "stderr_sha256": hashlib.sha256((result.get("stderr") or "").encode()).hexdigest()}

    def run(self, *, work: Sandbox, package: str, candidate_debs: dict[str, str],
            metadata: dict[str, str]) -> tuple[dict[str, Any], Sandbox]:
        spec = SPECS.get(package)
        if spec is None:
            raise ValueError(f"unsupported canary package: {package}")
        official = self.download_official(work, package, candidate_debs)
        judge_box = self.client.create({**metadata, "role": "judge", "template": JUDGE_TEMPLATE})
        if not official["passed"]:
            return self._failure("official_baseline_deb_unavailable", official), judge_box
        try:
            official_bytes = {part: self.client.filesystem_read_bytes(work, path)
                              for part, path in official["paths"].items()}
            candidate_bytes = {part: self.client.filesystem_read_bytes(work, path)
                               for part, path in candidate_debs.items()}
            if not all(official_bytes.values()) or not all(candidate_bytes.values()):
                return self._failure("empty_deb_artifact", official), judge_box
            official_path = "/workspace/judge/input/official.deb"
            official_dev_path = "/workspace/judge/input/official-dev.deb"
            candidate_path = "/workspace/judge/input/candidate.deb"
            candidate_dev_path = "/workspace/judge/input/candidate-dev.deb"
            script_path = "/workspace/judge/clean_canary_judge.py"
            output_path = "/workspace/judge/evidence.json"
            self.client.filesystem_write(judge_box, official_path, official_bytes["runtime"])
            self.client.filesystem_write(judge_box, official_dev_path, official_bytes["dev"])
            self.client.filesystem_write(judge_box, candidate_path, candidate_bytes["runtime"])
            self.client.filesystem_write(judge_box, candidate_dev_path, candidate_bytes["dev"])
            self.client.filesystem_write(judge_box, script_path, JUDGE_SCRIPT)
            command = " ".join(shlex.quote(value) for value in (
                "python3", script_path, package, spec.dev_package, official_path, official_dev_path,
                candidate_path, candidate_dev_path,
                spec.library, spec.smoke_symbol, output_path,
            ))
            execution = self.client.command(judge_box, command, timeout=600)
            try:
                payload = json.loads(self.client.filesystem_read(judge_box, output_path))
            except (ValueError, json.JSONDecodeError) as exc:
                return self._failure(f"missing_or_invalid_judge_evidence:{exc}", official), judge_box
            result = self.evaluate(payload)
            result["command_exit_code"] = execution.get("exit_code")
            expected_hashes = {
                "official_deb": hashlib.sha256(official_bytes["runtime"]).hexdigest(),
                "official_dev_deb": hashlib.sha256(official_bytes["dev"]).hexdigest(),
                "candidate_deb": hashlib.sha256(candidate_bytes["runtime"]).hexdigest(),
                "candidate_dev_deb": hashlib.sha256(candidate_bytes["dev"]).hexdigest(),
            }
            integrity_failures = []
            if execution.get("exit_code") != 0:
                integrity_failures.append("judge_command_failed")
            if payload.get("sha256") != expected_hashes:
                integrity_failures.append("transferred_deb_sha256_mismatch")
            expected_script_hash = hashlib.sha256(JUDGE_SCRIPT.encode()).hexdigest()
            if payload.get("environment", {}).get("judge_script_sha256") != expected_script_hash:
                integrity_failures.append("judge_script_sha256_mismatch")
            if integrity_failures:
                result["valid"] = False
                result["fence_passed"] = False
                result["failure_category"] = "JUDGE_EVIDENCE_INVALID"
                result["integrity_failures"] = integrity_failures
            result["evidence_refs"] = [output_path, official_path, official_dev_path,
                                       candidate_path, candidate_dev_path]
            result["official_download"] = official
            result["sandbox_policy"] = {"template": JUDGE_TEMPLATE, "llm": False,
                                        "allow_internet_access": False, "injected_secret_names": []}
            return result, judge_box
        except (OSError, RuntimeError, ValueError) as exc:
            return self._failure(f"judge_transport_failed:{exc}", official), judge_box

    @classmethod
    def evaluate(cls, payload: dict[str, Any]) -> dict[str, Any]:
        checks = payload.get("checks") if isinstance(payload.get("checks"), dict) else {}
        missing = sorted(cls.REQUIRED_CHECKS - checks.keys())
        failed = sorted(name for name in cls.REQUIRED_CHECKS if checks.get(name) is not True)
        anti_cheat = payload.get("anti_cheat") if isinstance(payload.get("anti_cheat"), dict) else {"invalid": True}
        environment = payload.get("environment") if isinstance(payload.get("environment"), dict) else {}
        secrets = environment.get("secret_env_names", ["missing_evidence"])
        hashes = payload.get("sha256") if isinstance(payload.get("sha256"), dict) else {}
        hashes_valid = all(isinstance(hashes.get(name), str) and len(hashes[name]) == 64
                           and all(char in "0123456789abcdef" for char in hashes[name].lower())
                           for name in ("official_deb", "official_dev_deb", "candidate_deb", "candidate_dev_deb"))
        findings = sorted(name for name, value in anti_cheat.items() if value)
        valid = (payload.get("schema") == "lda.canary-judge.v1" and payload.get("valid") is True
                 and not missing and not failed and not findings and secrets == [] and hashes_valid)
        failure = "" if valid else ("ABI_FAILURE" if failed else "JUDGE_EVIDENCE_INVALID")
        return {"valid": valid, "fence_passed": valid, "checks": checks,
                "missing_checks": missing, "failed_checks": failed,
                "anti_cheat": {"passed": not findings, "findings": findings},
                "environment": environment, "sha256": hashes,
                "failure_category": failure, "confidence": 1.0,
                "raw_evidence": payload}

    @staticmethod
    def _failure(reason: str, official: dict[str, Any] | None = None) -> dict[str, Any]:
        return {"valid": False, "fence_passed": False, "checks": {},
                "anti_cheat": {"passed": False, "findings": []},
                "failure_category": "JUDGE_EVIDENCE_INVALID", "reason": reason,
                "official_download": official or {}, "evidence_refs": [], "confidence": 1.0}
