from __future__ import annotations

from typing import Any
import hashlib

from lda.e2b.client import E2BClient, Sandbox
from lda.research.campaign import CampaignInput


class QualificationRunner:
    """Validates report candidates before they enter the Mission Graph."""

    def __init__(self, client: E2BClient):
        self.client = client
        self.base_template = "lda-base-lda-hm-as-prod-20260825-v12"

    def run(self, campaign: CampaignInput, run_id: str) -> dict[str, Any]:
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
            results = []
            for package in campaign.top10:
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
                            checks["source_mapping"] = {"available": "Source:" in stdout and "Version:" in stdout,
                                "derived_from_binary_metadata": True,
                                "source": next((x.split(":", 1)[1].strip() for x in stdout.splitlines() if x.startswith("Source:")), None),
                                "source_version": next((x.split(":", 1)[1].strip() for x in stdout.splitlines() if x.startswith("Version:")), None)}
                    except Exception as exc:
                        checks[name] = {"available": False, "error": str(exc)}
                # Profiling and replacement remain explicit gates; no report rank bypasses them.
                results.append({"package": package, "checks": checks,
                                "report_unresolved_edges": campaign.report_stats["unresolved_edges"],
                                "unresolved_edges_verified": False,
                                "source_snapshot_verified": False,
                                "hotspot_verified": False, "micro_benchmark_verified": False,
                                "e2e_verified": False, "deb_replace_verified": False,
                                "status": "QUALIFICATION_PENDING"})
            return {"campaign_sha256": campaign.sha256, "e2b_copy_sha256": uploaded_hash, "e2b_path": campaign.e2b_path,
                    "base_template": self.base_template, "results": results, "canary": list(campaign.canary),
                    "status": "QUALIFICATION_PENDING", "release_blockers": [
                        "fixed Sources Snapshot verification", "unresolved edge verification",
                        "clean source rebuild", "stable hotspot profile", "micro benchmark",
                        "portfolio E2E", ".deb replacement and rollback"]}
        finally:
            self.client.kill(sandbox)
