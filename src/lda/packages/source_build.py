"""Deterministic Debian source acquisition and build inside E2B."""

from __future__ import annotations

import hashlib
import re
import shlex
from dataclasses import dataclass
from typing import Any

from lda.benchmarks.canary import validate_optimization_flags
from lda.e2b.client import E2BClient, Sandbox


@dataclass(frozen=True)
class PackageBuildSpec:
    package: str
    source_package: str
    dev_packages: tuple[str, ...] = ()


SPECS: dict[str, PackageBuildSpec] = {
    "libgtk-4-1": PackageBuildSpec("libgtk-4-1", "gtk4", ("libgtk-4-dev",)),
    "libgtk-3-0t64": PackageBuildSpec("libgtk-3-0t64", "gtk+3.0", ("libgtk-3-dev",)),
    "gnome-shell": PackageBuildSpec("gnome-shell", "gnome-shell"),
    "libreoffice-core": PackageBuildSpec("libreoffice-core", "libreoffice", ("libreoffice-dev",)),
    # sssd-common has no corresponding development package. The source emits
    # several independently versioned public development interfaces, which a
    # package-specific Judge must select according to the optimized component.
    "sssd-common": PackageBuildSpec("sssd-common", "sssd"),
    "gnome-settings-daemon": PackageBuildSpec(
        "gnome-settings-daemon", "gnome-settings-daemon", ("gnome-settings-daemon-dev",)),
    # gst-plugins-good1.0 exports runtime plugins but no development package.
    "gstreamer1.0-plugins-good": PackageBuildSpec(
        "gstreamer1.0-plugins-good", "gst-plugins-good1.0"),
    "ibus": PackageBuildSpec("ibus", "ibus", ("libibus-1.0-dev",)),
}


class DebianSourceBuilder:
    """Build an exact Ubuntu source version selected by Qualification.

    The adapter never guesses source identity from a package name. Both the
    package-to-source mapping and fixed snapshot must already have passed
    Qualification. Commands run only in the supplied disposable E2B workspace.
    """

    def __init__(self, client: E2BClient, qualification: dict[str, Any]):
        self.client = client
        self.qualification = qualification

    @staticmethod
    def _evidence(result: dict[str, Any]) -> dict[str, Any]:
        stdout = result.get("stdout") or ""
        stderr = result.get("stderr") or ""
        return {
            "exit_code": result.get("exit_code"),
            "stdout_sha256": hashlib.sha256(stdout.encode()).hexdigest(),
            "stderr_sha256": hashlib.sha256(stderr.encode()).hexdigest(),
            "stdout_tail": stdout[-3000:],
            "stderr_tail": stderr[-3000:],
        }

    def _resolve(self, package: str) -> tuple[PackageBuildSpec, str]:
        spec = SPECS.get(package)
        if spec is None:
            raise ValueError(f"unsupported generic package: {package}")
        snapshot = self.qualification.get("sources_snapshot", {})
        if snapshot.get("verified") is not True or not snapshot.get("snapshot"):
            raise ValueError("fixed Sources Snapshot was not verified by Qualification")
        if not re.fullmatch(r"[0-9]{8}T[0-9]{6}Z", str(snapshot["snapshot"])):
            raise ValueError("fixed Sources Snapshot identifier is invalid")
        row = next((item for item in self.qualification.get("results", [])
                    if item.get("package") == package), None)
        if row is None or row.get("source_snapshot_verified") is not True:
            raise ValueError(f"source snapshot was not verified for {package}")
        mapping = row.get("checks", {}).get("source_mapping", {})
        if mapping.get("available") is not True:
            raise ValueError(f"verified source mapping is missing for {package}")
        source = (mapping.get("source") or "").split()[0]
        version = mapping.get("source_version") or ""
        if source != spec.source_package or not version:
            raise ValueError(
                f"Qualification source mismatch for {package}: expected {spec.source_package}, got {source or 'missing'}")
        return spec, version

    def _run(self, sandbox: Sandbox, command: str, *, timeout: int) -> dict[str, Any]:
        result = self.client.command(sandbox, command, timeout=timeout)
        return result

    def build(self, sandbox: Sandbox, package: str,
              *, cflags: list[str] | tuple[str, ...] | None = None,
              cxxflags: list[str] | tuple[str, ...] | None = None,
              build_root: str = "/workspace/generic-source-build") -> dict[str, Any]:
        try:
            spec, version = self._resolve(package)
        except ValueError as exc:
            return {"passed": False, "status": "QUALIFICATION_REJECTED", "reason": str(exc),
                    "artifacts": [], "runtime_artifact": None, "dev_artifacts": {}}
        try:
            safe_cflags = " ".join(validate_optimization_flags(cflags))
            safe_cxxflags = " ".join(validate_optimization_flags(cxxflags))
        except ValueError as exc:
            return {"passed": False, "status": "POLICY_REJECTED", "reason": str(exc),
                    "artifacts": [], "runtime_artifact": None, "dev_artifacts": {}}

        snapshot = self.qualification["sources_snapshot"]["snapshot"]
        base = f"https://snapshot.ubuntu.com/ubuntu/{snapshot}/"
        source_lines = "\n".join(
            f"{kind} {base} {suite} main universe multiverse restricted"
            for kind in ("deb", "deb-src")
            for suite in ("resolute", "resolute-updates", "resolute-security")
        ) + "\n"
        safe = package.replace("/", "_")
        root = f"{build_root}/{safe}"
        downloads = f"{root}/downloads"
        source_tree = f"{root}/source"
        apt_list = f"/etc/apt/sources.list.d/lda-{safe}-snapshot.list"
        apt_scope = (f"-o Dir::Etc::sourcelist={shlex.quote(apt_list)} "
                     "-o Dir::Etc::sourceparts=- -o APT::Get::Assume-Yes=true")
        evidence: dict[str, Any] = {
            "passed": False,
            "package": package,
            "source_package": spec.source_package,
            "source_version": version,
            "snapshot": snapshot,
            "artifacts": [],
            "runtime_artifact": None,
            "dev_artifacts": {},
            "strategy": {"cflags": safe_cflags.split(), "cxxflags": safe_cxxflags.split()},
        }

        encoded = __import__("base64").b64encode(source_lines.encode()).decode()
        setup = self._run(sandbox,
            f"rm -rf {shlex.quote(root)} && mkdir -p {shlex.quote(downloads)} && "
            f"printf %s {shlex.quote(encoded)} | base64 -d > {shlex.quote(apt_list)} && "
            f"DEBIAN_FRONTEND=noninteractive apt-get {apt_scope} update",
            timeout=900)
        evidence["snapshot_setup"] = self._evidence(setup)
        if setup.get("exit_code") != 0:
            evidence.update(status="SNAPSHOT_SETUP_FAILED", reason="fixed snapshot apt update failed")
            return evidence

        exact = f"{spec.source_package}={version}"
        fetch = self._run(sandbox,
            f"cd {shlex.quote(downloads)} && apt-get {apt_scope} source --download-only {shlex.quote(exact)}",
            timeout=1800)
        evidence["source_fetch"] = self._evidence(fetch)
        if fetch.get("exit_code") != 0:
            evidence.update(status="SOURCE_FETCH_FAILED", reason="exact source version download failed")
            return evidence

        dsc_result = self._run(sandbox,
            f"find {shlex.quote(downloads)} -maxdepth 1 -type f -name '*.dsc' -print | sort",
            timeout=120)
        dsc_paths = [line.strip() for line in (dsc_result.get("stdout") or "").splitlines() if line.strip()]
        evidence["dsc_listing"] = self._evidence(dsc_result)
        if dsc_result.get("exit_code") != 0 or len(dsc_paths) != 1:
            evidence.update(status="SOURCE_IDENTITY_INVALID", reason="exactly one downloaded dsc is required")
            return evidence
        dsc = dsc_paths[0]
        unpack = self._run(sandbox,
            f"dpkg-source -x {shlex.quote(dsc)} {shlex.quote(source_tree)}",
            timeout=900)
        evidence["dsc"] = dsc
        evidence["unpack"] = self._evidence(unpack)
        if unpack.get("exit_code") != 0:
            evidence.update(status="SOURCE_UNPACK_FAILED", reason="dpkg-source failed")
            return evidence

        version_check = self._run(sandbox,
            f"cd {shlex.quote(source_tree)} && test \"$(dpkg-parsechangelog -SVersion)\" = {shlex.quote(version)}",
            timeout=120)
        evidence["version_check"] = self._evidence(version_check)
        if version_check.get("exit_code") != 0:
            evidence.update(status="SOURCE_IDENTITY_INVALID", reason="unpacked source version differs from Qualification")
            return evidence

        deps = self._run(sandbox,
            f"DEBIAN_FRONTEND=noninteractive apt-get {apt_scope} build-dep {shlex.quote(exact)}",
            timeout=3600)
        evidence["build_dep_install"] = self._evidence(deps)
        if deps.get("exit_code") != 0:
            evidence.update(status="BUILD_DEPS_INSTALL_FAILED", reason="snapshot build dependencies unavailable")
            return evidence
        deps_check = self._run(sandbox,
            f"cd {shlex.quote(source_tree)} && dpkg-checkbuilddeps", timeout=300)
        evidence["build_deps_check"] = self._evidence(deps_check)
        if deps_check.get("exit_code") != 0:
            evidence.update(status="BUILD_DEPS_UNSATISFIED", reason="dpkg-checkbuilddeps failed after installation")
            return evidence

        build = self._run(sandbox,
            f"cd {shlex.quote(source_tree)} && "
            f"DEB_CFLAGS_MAINT_APPEND={shlex.quote(safe_cflags)} "
            f"DEB_CXXFLAGS_MAINT_APPEND={shlex.quote(safe_cxxflags)} "
            "dpkg-buildpackage -us -uc -b",
            timeout=14400 if package == "libreoffice-core" else 3600)
        evidence["build"] = self._evidence(build)
        if build.get("exit_code") != 0:
            evidence.update(status="BUILD_FAILED", reason="dpkg-buildpackage failed")
            return evidence

        listing = self._run(sandbox,
            f"find {shlex.quote(root)} -maxdepth 2 -type f -name '*.deb' -print | sort",
            timeout=120)
        artifacts = [line.strip() for line in (listing.get("stdout") or "").splitlines() if line.strip()]
        evidence["artifact_listing"] = self._evidence(listing)
        metadata: list[dict[str, str]] = []
        for artifact in artifacts:
            fields = self._run(sandbox,
                f"dpkg-deb -f {shlex.quote(artifact)} Package Version Architecture", timeout=120)
            values = (fields.get("stdout") or "").splitlines()
            if fields.get("exit_code") == 0 and len(values) >= 3:
                hashed = self._run(sandbox, f"sha256sum {shlex.quote(artifact)}", timeout=120)
                metadata.append({"path": artifact, "package": values[0].strip(),
                                 "version": values[1].strip(), "architecture": values[2].strip(),
                                 "sha256": (hashed.get("stdout") or "").split()[0] if hashed.get("exit_code") == 0 else ""})
        evidence["artifacts"] = metadata
        runtime = next((item for item in metadata
                        if item["package"] == spec.package and item["version"] == version), None)
        dev = {name: next((item for item in metadata
                          if item["package"] == name and item["version"] == version), None)
               for name in spec.dev_packages}
        evidence["runtime_artifact"] = runtime["path"] if runtime else None
        evidence["dev_artifacts"] = {name: item["path"] for name, item in dev.items() if item}
        if runtime is None:
            evidence.update(status="TARGET_RUNTIME_DEB_MISSING", reason="target runtime package was not built")
            return evidence
        missing_dev = [name for name, item in dev.items() if item is None]
        if missing_dev:
            evidence.update(status="TARGET_DEV_DEB_MISSING",
                            reason="required development package was not built: " + ", ".join(missing_dev))
            return evidence
        evidence.update(passed=True, status="BUILT", reason=None)
        return evidence
