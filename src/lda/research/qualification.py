from __future__ import annotations

from pathlib import Path
from typing import Any
import hashlib
import json

from lda.e2b.client import E2BClient, Sandbox
from lda.research.campaign import CampaignInput


class QualificationRunner:
    """Validates report candidates before they enter the Mission Graph."""

    def __init__(self, client: E2BClient):
        self.client = client
        self.base_template = "lda-base-lda-hm-as-prod-20260825-v12"
        self.snapshot = "20260825T000000Z"

    def _snapshot_root(self, campaign: CampaignInput) -> Path | None:
        """Resolve the checked-in, immutable source bundle without trusting cwd."""
        configured = Path(__import__("os").environ["LDA_SOURCE_SNAPSHOT_ROOT"]).expanduser() \
            if __import__("os").environ.get("LDA_SOURCE_SNAPSHOT_ROOT") else None
        candidates = [
            configured,
            Path.cwd() / "source_snapshot" / self.snapshot,
            Path(__file__).resolve().parents[3] / "source_snapshot" / self.snapshot,
            Path(campaign.source_path).resolve().parent / "source_snapshot" / self.snapshot,
            Path(campaign.source_path).resolve().parent / "source-snapshot" / self.snapshot,
        ]
        for candidate in candidates:
            if candidate and (candidate / "SHA256SUMS").is_file():
                return candidate
        return None

    def _bootstrap_snapshot(self, sandbox: Sandbox) -> dict[str, Any]:
        source_file = "/etc/apt/sources.list.d/lda-snapshot.list"
        # The snapshot endpoint is intentionally checked, never treated as
        # authoritative merely because apt-get returned a zero exit status.
        base = f"https://snapshot.ubuntu.com/ubuntu/{self.snapshot}/"
        content = "\n".join(
            f"{kind} {base} {suite} main universe multiverse restricted"
            for kind in ("deb", "deb-src")
            for suite in ("resolute", "resolute-updates", "resolute-security")
        ) + "\n"
        encoded = __import__("base64").b64encode(content.encode()).decode()
        result = self.client.command(sandbox, f"printf %s {encoded} | base64 -d > {source_file} && apt-get update",
                                     timeout=600)
        release = self.client.command(sandbox, "apt-cache policy libcairo2 libsoup-3.0-0", timeout=120)
        indexes = self.client.command(sandbox, "apt-get indextargets", timeout=120)
        index_output = indexes.get("stdout") or ""
        has_source_index = "Target-Of: deb-src" in index_output or "Created-By: Sources" in index_output
        release_output = release.get("stdout") or ""
        return {
            "snapshot": self.snapshot,
            "source_file": source_file,
            "update_exit_code": result.get("exit_code"),
            "update_stderr_sha256": hashlib.sha256((result.get("stderr") or "").encode()).hexdigest(),
            "release_exit_code": release.get("exit_code"),
            "release_stdout_sha256": hashlib.sha256(release_output.encode()).hexdigest(),
            "source_index": has_source_index,
            "verified": result.get("exit_code") == 0 and release.get("exit_code") == 0 and has_source_index,
            "evidence_ref": source_file,
        }

    def _upload_source_bundle(self, sandbox: Sandbox, campaign: CampaignInput) -> dict[str, Any]:
        """Upload the pinned canary source files because the base data plane has no archive egress."""
        root = self._snapshot_root(campaign)
        if root is None:
            return {"available": False, "reason": "missing checked-in source snapshot bundle"}
        manifest = root / "SHA256SUMS"
        if not manifest.is_file():
            return {"available": False, "reason": f"missing source snapshot bundle: {manifest}"}
        uploaded: list[dict[str, str]] = []
        directories = {f"/workspace/source-snapshot/{self.snapshot}/{Path(line.split('  ', 1)[1]).parent}"
                       for line in manifest.read_text(encoding="utf-8").splitlines() if line.strip()}
        if directories:
            self.client.command(sandbox, "mkdir -p " + " ".join(sorted(directories)))
        for line in manifest.read_text(encoding="utf-8").splitlines():
            digest, relative = line.split("  ", 1)
            source = root / relative
            if not source.is_file():
                return {"available": False, "reason": f"missing source snapshot file: {source}"}
            data = source.read_bytes()
            if hashlib.sha256(data).hexdigest() != digest:
                return {"available": False, "reason": f"source snapshot hash mismatch: {source}"}
            target = f"/workspace/source-snapshot/{self.snapshot}/{relative}"
            self.client.filesystem_write(sandbox, target, data)
            uploaded.append({"path": target, "sha256": digest})
        return {"available": True, "snapshot": self.snapshot, "files": uploaded,
                "manifest_sha256": hashlib.sha256(manifest.read_bytes()).hexdigest()}

    @staticmethod
    def _command_evidence(result: dict[str, Any]) -> dict[str, Any]:
        stdout = result.get("stdout") or ""
        stderr = result.get("stderr") or ""
        return {
            "exit_code": result.get("exit_code"),
            "stdout_sha256": hashlib.sha256(stdout.encode()).hexdigest(),
            "stderr_sha256": hashlib.sha256(stderr.encode()).hexdigest(),
            "stdout_tail": stdout[-3000:],
            "stderr_tail": stderr[-3000:],
        }

    def _source_build(self, sandbox: Sandbox, source_name: str, source_bundle: dict[str, Any]) -> dict[str, Any]:
        """Unpack and attempt a clean build from the pinned bundle in E2B."""
        files = source_bundle.get("files", []) if source_bundle.get("available") else []
        dsc = next((item["path"] for item in files if item["path"].endswith(".dsc") and f"/{source_name}/" in item["path"]), None)
        if not dsc:
            return {"status": "UNAVAILABLE", "source": source_name, "reason": "source dsc not uploaded"}
        safe = source_name.replace("/", "_")
        root = f"/workspace/source-build/{safe}"
        unpack = self.client.command(sandbox, f"rm -rf {root} && mkdir -p {root} && dpkg-source -x {dsc} {root}/source",
                                     timeout=300)
        evidence: dict[str, Any] = {"source": source_name, "dsc": dsc, "unpack": self._command_evidence(unpack)}
        if unpack.get("exit_code") != 0:
            evidence["status"] = "UNPACK_FAILED"
            return evidence
        check = self.client.command(sandbox, f"cd {root}/source && dpkg-checkbuilddeps", timeout=300)
        evidence["build_deps"] = self._command_evidence(check)
        if check.get("exit_code") != 0:
            install = self.client.command(sandbox,
                "apt-get -o Dir::Etc::sourcelist=/etc/apt/sources.list.d/lda-snapshot.list "
                "-o Dir::Etc::sourceparts=- -o APT::Get::Assume-Yes=true "
                f"build-dep {source_name}", timeout=1800)
            evidence["build_dep_install"] = self._command_evidence(install)
            check = self.client.command(sandbox, f"cd {root}/source && dpkg-checkbuilddeps", timeout=300)
            evidence["build_deps_after_install"] = self._command_evidence(check)
            if check.get("exit_code") != 0:
                evidence["status"] = "BUILD_DEPS_UNAVAILABLE" if install.get("exit_code") == 0 else "BUILD_DEPS_INSTALL_FAILED"
                return evidence
        build = self.client.command(sandbox, f"cd {root}/source && DEB_BUILD_OPTIONS=nocheck dpkg-buildpackage -us -uc -b", timeout=1800)
        evidence["build"] = self._command_evidence(build)
        artifacts = self.client.command(sandbox, f"find {root} -maxdepth 2 -type f -name '*.deb' -printf '%f %s\\n' | sort",
                                        timeout=120)
        evidence["debs"] = self._command_evidence(artifacts)
        evidence["status"] = "BUILT" if build.get("exit_code") == 0 else "BUILD_FAILED"
        return evidence

    def run(self, campaign: CampaignInput, run_id: str,
            checkpoint_path: str | Path | None = None) -> dict[str, Any]:
        sandbox = self.client.create({"project": "lda", "run_id": run_id, "life_cycle": "qualification",
            "mission_id": "qualification", "candidate_id": "none", "role": "qualification",
            "template": self.base_template, "lease_id": "qualification-" + run_id})
        try:
            raw = open(campaign.source_path, encoding="utf-8").read()
            self.client.filesystem_write(sandbox, campaign.e2b_path, raw)
            uploaded = self.client.filesystem_read(sandbox, campaign.e2b_path)
            uploaded_hash = hashlib.sha256(uploaded.encode()).hexdigest()
            if uploaded_hash != campaign.sha256:
                raise RuntimeError("E2B campaign input hash mismatch after upload")
            source_bundle = self._upload_source_bundle(sandbox, campaign)
            snapshot = self._bootstrap_snapshot(sandbox)
            checkpoint = Path(checkpoint_path) if checkpoint_path else None
            prior_results: dict[str, dict[str, Any]] = {}
            if checkpoint and checkpoint.is_file():
                try:
                    prior = json.loads(checkpoint.read_text(encoding="utf-8"))
                    if prior.get("campaign_sha256") == campaign.sha256:
                        prior_results = {row["package"]: row for row in prior.get("results", [])
                                         if isinstance(row, dict) and row.get("package")}
                except (OSError, ValueError, json.JSONDecodeError):
                    prior_results = {}
            results = []
            for package in campaign.top10:
                prior_row = prior_results.get(package)
                if prior_row and (package not in campaign.canary or prior_row.get("clean_source_rebuild_verified") is True):
                    results.append(prior_row)
                    continue
                commands = {
                    "binary_package": f"apt-cache show {package}",
                    "dependency_metadata": f"apt-cache depends {package}",
                    "build_tools": "command -v dpkg-buildpackage && command -v cmake && command -v gcc",
                }
                checks = {}
                for name, command in commands.items():
                    try:
                        output = self.client.command(sandbox, command)
                        stdout = output.get("stdout") or ""
                        checks[name] = {"exit_code": output.get("exit_code"), "available": output.get("exit_code") == 0,
                                        "stdout_sha256": __import__("hashlib").sha256(stdout.encode()).hexdigest()}
                        if name == "binary_package":
                            binary_name = next((x.split(":", 1)[1].strip() for x in stdout.splitlines()
                                                if x.startswith("Package:")), None)
                            source_name = next((x.split(":", 1)[1].strip() for x in stdout.splitlines()
                                                if x.startswith("Source:")), None) or binary_name
                            source_version = next((x.split(":", 1)[1].strip() for x in stdout.splitlines()
                                                   if x.startswith("Version:")), None)
                            checks["source_mapping"] = {"available": bool(source_name and source_version),
                                "derived_from_binary_metadata": True,
                                "implicit_same_name": "Source:" not in stdout,
                                "source": source_name,
                                "source_version": source_version}
                    except Exception as exc:
                        checks[name] = {"available": False, "error": str(exc)}
                source_name = checks.get("source_mapping", {}).get("source")
                if source_name:
                    source_name = source_name.split()[0]
                source_check = {"available": False, "source": source_name}
                if source_name and snapshot["verified"]:
                    try:
                        source_result = self.client.command(sandbox, f"apt-cache showsrc {source_name}")
                        source_check = {"available": source_result.get("exit_code") == 0,
                                        "source": source_name,
                                        "stdout_sha256": hashlib.sha256((source_result.get("stdout") or "").encode()).hexdigest()}
                    except Exception as exc:
                        source_check = {"available": False, "source": source_name, "error": str(exc)}
                if source_name and source_bundle.get("available"):
                    bundle_files = [x["path"] for x in source_bundle["files"] if f"/{source_name}/" in x["path"]]
                    source_check["bundle_files"] = bundle_files
                    source_check["bundle_available"] = bool(bundle_files)
                    source_check["available"] = source_check.get("available", False) or bool(bundle_files)
                checks["source_snapshot"] = source_check
                if package in campaign.canary:
                    checks["source_build"] = self._source_build(sandbox, source_name or "unknown", source_bundle)
                # Profiling and replacement remain explicit gates; no report rank bypasses them.
                source_build = checks.get("source_build", {})
                source_snapshot_verified = bool(snapshot["verified"] and source_check.get("available"))
                source_unpack_verified = (
                    package in campaign.canary
                    and source_build.get("status") not in {"UNAVAILABLE", "UNPACK_FAILED", "BUILD_DEPS_INSTALL_FAILED"}
                    and bool(source_build.get("unpack", {}).get("exit_code") == 0)
                )
                clean_source_rebuild_verified = package in campaign.canary and source_build.get("status") == "BUILT"
                evidence_refs: list[str] = []
                if source_snapshot_verified:
                    evidence_refs.append(snapshot.get("evidence_ref", "fixed-sources-snapshot"))
                if source_check.get("bundle_files"):
                    evidence_refs.extend(source_check["bundle_files"])
                row = {"package": package, "checks": checks,
                       "report_unresolved_edges": campaign.report_stats["unresolved_edges"],
                       "unresolved_edges_verified": False,
                       "source_snapshot_verified": source_snapshot_verified,
                       "source_snapshot_verified_evidence_refs": evidence_refs,
                       # Keep both spellings in artifacts for compatibility.
                       "source_unpack_verified": source_unpack_verified,
                       "source_unpacked_verified": source_unpack_verified,
                       "source_unpack_verified_evidence_refs": ([source_build.get("dsc", "")] if source_unpack_verified else []),
                       "source_unpacked_verified_evidence_refs": ([source_build.get("dsc", "")] if source_unpack_verified else []),
                       "clean_source_rebuild_verified": clean_source_rebuild_verified,
                       "clean_source_rebuild_verified_evidence_refs": ([source_build.get("dsc", "")] if clean_source_rebuild_verified else []),
                       "hotspot_verified": False, "micro_benchmark_verified": False,
                       "e2e_verified": False, "deb_replace_verified": False,
                       "rollback_verified": False, "status": "QUALIFICATION_PENDING"}
                results.append(row)
                if checkpoint:
                    checkpoint.parent.mkdir(parents=True, exist_ok=True)
                    checkpoint.write_text(json.dumps({
                        "campaign_sha256": campaign.sha256, "e2b_copy_sha256": uploaded_hash,
                        "e2b_path": campaign.e2b_path, "base_template": self.base_template,
                        "sources_snapshot": snapshot, "source_bundle": source_bundle,
                        "results": results, "canary": list(campaign.canary),
                        "status": "QUALIFICATION_RUNNING",
                    }, indent=2, sort_keys=True) + "\n", encoding="utf-8")
            return {"campaign_sha256": campaign.sha256, "e2b_copy_sha256": uploaded_hash, "e2b_path": campaign.e2b_path,
                    "base_template": self.base_template, "sources_snapshot": snapshot,
                    "source_bundle": source_bundle,
                    "results": results, "canary": list(campaign.canary),
                    "status": "QUALIFICATION_PENDING", "release_blockers": [
                        "fixed Sources Snapshot verification", "unresolved edge verification",
                        "clean source rebuild", "stable hotspot profile", "micro benchmark",
                        "portfolio E2E", ".deb replacement and rollback"]}
        finally:
            self.client.kill(sandbox)
