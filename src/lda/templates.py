from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import Any, Callable

from lda.config.templates import TemplateAliases
from lda.e2b.client import E2BClient
from lda.e2b.gateway import GatewayConfig, SharedGateway


TEMPLATES = {
    "lda-controller": {"roles": ["Argus Supervisor", "LDA Mission Runtime", "Mission Scheduler", "Policy Engine", "AgentFactory", "E2B Client", "Tool Gateway", "World State", "Outcome Ledger", "Capability Registry", "State Store", "Artifact Store", "Secret Redactor"]},
    "lda-agent-runtime": {
        "roles": ["Codex SDK/CLI", "Agent Runner", "JSON Schema", "MCP Client", "Role Prompt", "Intel Performance Skills"],
        "codex_release": "0.149.1",
        "intel_performance_skills_commit": "e9d0b6410fb1ad7a50fb81e0868fd23ae886882c",
    },
    "lda-base": {
        "tools": ["Ubuntu 26.04", "GCC", "Clang", "LLD", "CMake", "Ninja", "Meson", "autotools", "debhelper", "perf", "strace", "valgrind", "bpftrace", "numactl", "abi-compliance-checker", "abidiff", "C/C++/Python/Rust FFI", "Benchmark Harness", "Intel Performance Skills"],
        "intel_performance_skills_commit": "e9d0b6410fb1ad7a50fb81e0868fd23ae886882c",
    },
    "lda-judge": {"checks": ["ABI/API/FFI Fence", "self test", "reverse dependency", "benchmark", "anti-cheat", "package install/rollback", "runtime and development package parity", "SONAME/exported symbols/symbol versions/NEEDED", "headers/pkg-config", "precompiled dlopen/dlsym and ctypes"], "llm": False},
    "lda-e2e": {
        "tools": ["Chrome", "Playwright 1.55.0", "Web server", "GUI", "system workload"],
        "harness": "/usr/local/bin/run-portfolio-e2e",
        "schema": "lda.portfolio-e2e.v1",
        "network_scope": "loopback-only",
        "secrets": False,
    },
}

TEMPLATE_VERSIONS = {"lda-e2e": "2"}


def _manifest(name: str) -> dict[str, Any]:
    manifest = {"name": name, "version": TEMPLATE_VERSIONS.get(name, "1"), **TEMPLATES[name]}
    canonical = json.dumps(manifest, sort_keys=True, separators=(",", ":")).encode()
    manifest["spec_hash"] = hashlib.sha256(canonical).hexdigest()
    return manifest


def expected_template_manifests(aliases: TemplateAliases | None = None) -> dict[str, dict[str, Any]]:
    resolved = aliases or TemplateAliases()
    manifests: dict[str, dict[str, Any]] = {}
    for name in TEMPLATES:
        manifest = _manifest(name)
        manifest["alias"] = resolved.alias_for(name)
        manifests[name] = manifest
    return manifests


def _connection_options(gateway: SharedGateway) -> dict[str, Any]:
    gateway.install_sdk_adapter()
    return {
        "api_key": gateway.api_key,
        "api_url": gateway.config.api_url,
        "sandbox_url": gateway.config.sandbox_url,
        "headers": gateway.headers(),
    }


def _remote_manifest(client: E2BClient, alias: str, name: str) -> dict[str, Any]:
    sandbox = client.create({
        "project": "lda",
        "run_id": "template-build",
        "life_cycle": "template-check",
        "mission_id": name,
        "candidate_id": "none",
        "role": "template-check",
        "template": alias,
        "lease_id": f"template-check-{alias}",
        "timeout": "300",
    })
    try:
        return json.loads(client.filesystem_read(sandbox, "/opt/lda/template-manifest.json"))
    finally:
        client.kill(sandbox)


def publish_template(path: Path, manifest: dict[str, Any]) -> str:
    """Build or reuse one version-checked E2B template alias."""
    from e2b import Template

    gateway = SharedGateway(GatewayConfig.from_env())
    if not gateway.api_key:
        raise RuntimeError("E2B_API_KEY is required to build templates")
    alias = str(manifest.get("alias") or manifest["name"])
    options = _connection_options(gateway)
    client = E2BClient(gateway)
    exists = Template.alias_exists(alias, **options)
    if exists:
        try:
            remote = _remote_manifest(client, alias, manifest["name"])
        except (OSError, RuntimeError, ValueError, json.JSONDecodeError):
            remote = {}
        if remote.get("version") == manifest["version"] and remote.get("spec_hash") == manifest["spec_hash"]:
            return "reused"

    dockerfile = path / "Dockerfile"
    if not dockerfile.is_file():
        raise RuntimeError(f"template Dockerfile is missing: {dockerfile}")
    previous_cwd = Path.cwd()
    try:
        os.chdir(path)
        builder = Template().from_dockerfile("Dockerfile")
        resources = {
            "lda-base": (8, 16384),
            "lda-e2e": (4, 8192),
            "lda-judge": (4, 8192),
        }
        cpu_count, memory_mb = resources.get(manifest["name"], (2, 4096))
        Template.build(builder, alias=alias, cpu_count=cpu_count, memory_mb=memory_mb,
                       skip_cache=exists, **options)
    finally:
        os.chdir(previous_cwd)
    remote = _remote_manifest(client, alias, manifest["name"])
    if remote.get("version") != manifest["version"] or remote.get("spec_hash") != manifest["spec_hash"]:
        raise RuntimeError(f"template version verification failed after build: {alias}")
    return "built"


def build_templates(root: str | Path, names: list[str] | None = None, *,
                    publisher: Callable[[Path, dict[str, Any]], str] | None = None,
                    aliases: TemplateAliases | None = None) -> list[str]:
    root = Path(root)
    template_root = root / "e2b_templates"
    built: list[str] = []
    manifests = expected_template_manifests(aliases)
    for name in names or list(TEMPLATES):
        if name not in TEMPLATES:
            raise ValueError(f"unknown template: {name}")
        path = template_root / name
        path.mkdir(parents=True, exist_ok=True)
        manifest = manifests[name]
        disk_manifest = {key: value for key, value in manifest.items() if key != "alias"}
        (path / "manifest.json").write_text(
            json.dumps(disk_manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        (publisher or publish_template)(path, manifest)
        built.append(name)
    return built
