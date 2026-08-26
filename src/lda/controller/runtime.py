"""Entry point executed inside the ``lda-controller`` E2B sandbox."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from typing import Any

from lda.config.templates import TemplateAliases
from lda.controller.protocol import ControllerProxyClient
from lda.controller.supervisor import ArgusSupervisor
from lda.research.campaign import CampaignInput
from lda.research.qualification import QualificationRunner
from lda.research.release import evaluate_canary_release
from lda.state.store import EventStore


def run_controller(config: dict[str, Any]) -> dict[str, Any]:
    if config.get("protocol_version") != 1:
        raise RuntimeError("unsupported Controller protocol version")
    run_id = str(config["run_id"])
    root = Path(config["run_root"]).resolve()
    root.mkdir(parents=True, exist_ok=True)
    os.environ["LDA_SOURCE_SNAPSHOT_ROOT"] = str(config["source_snapshot_root"])
    templates = TemplateAliases.from_mapping(config.get("templates"))
    client = ControllerProxyClient(str(config["request_path"]), str(config["response_path"]))
    store = EventStore(root)
    qualification_path = root / ".lda" / "artifacts" / "qualification.json"

    if store.world_path.is_file():
        supervisor = ArgusSupervisor(root, client=client, world=store.load_world(), templates=templates)
    else:
        campaign = CampaignInput(**config["campaign"])
        qualification = QualificationRunner(client, templates=templates).run(
            campaign, run_id, checkpoint_path=qualification_path)
        qualification["qualification_blockers"] = list(qualification.get("release_blockers", []))
        release = evaluate_canary_release(qualification, campaign.canary)
        qualification.update(release)
        qualification_path.parent.mkdir(parents=True, exist_ok=True)
        qualification_path.write_text(
            json.dumps(qualification, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        if not release["canary_release_ready"]:
            raise RuntimeError("Campaign stopped before canary missions; Qualification remains fail closed")
        supervisor = ArgusSupervisor.bootstrap(
            root, run_id, client=client, packages=release["eligible_packages"],
            campaign=campaign.dump(), qualification=qualification, templates=templates)

    cycles = supervisor.run()
    result = {
        "run_id": run_id, "cycles": len(cycles), "converged": not supervisor.world.active,
        "reason": supervisor.world.convergence_signals.get("reason"),
        "controller_execution": "e2b-sandbox",
    }
    result_path = root / ".lda" / "controller-result.json"
    result_path.parent.mkdir(parents=True, exist_ok=True)
    result_path.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="lda-controller-runtime")
    parser.add_argument("--config", required=True)
    args = parser.parse_args(argv)
    config = json.loads(Path(args.config).read_text(encoding="utf-8"))
    print(json.dumps(run_controller(config), sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
