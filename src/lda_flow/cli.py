"""Installed `lda-flow` command line interface."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import yaml

from .gateway import create_sandbox, require_e2b
from .lifecycle import build, prepare, verify
from .models import Campaign, Command, E2BSettings, Mission
from .orchestrator import CampaignController, SandboxExecutor


def _print_dry_run(controller: CampaignController) -> None:
    result = controller.dry_run()
    print(
        json.dumps(
            {
                "selected": result.selected,
                "skipped": result.skipped,
                "ranking": [
                    {"id": item.mission.id, "score": item.score, "components": item.components}
                    for item in result.ranked
                ],
            },
            indent=2,
        )
    )


def _load_mission(path: str) -> Mission:
    raw = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    return Mission.model_validate(raw)


def _run_mission_action(action: str, mission: Mission, output: Path) -> dict:
    settings = E2BSettings()
    require_e2b(settings)
    handle = create_sandbox(settings, ())
    executor = SandboxExecutor(handle)
    output.mkdir(parents=True, exist_ok=True)
    if action == "prepare":
        fences = prepare(mission, executor)
    elif action == "build":
        fences = build(mission, executor)
    else:
        trace_remote = "/workspace/mission/humanize.trace.jsonl"
        executor.run(
            Command(
                argv=(
                    "bash",
                    "-lc",
                    "hmz trace collect /workspace/mission --all --output " + trace_remote,
                ),
                timeout_seconds=600,
            )
        )
        trace = output / "humanize.trace.jsonl"
        trace.write_text(executor.read_text(trace_remote), encoding="utf-8")
        fences = verify(mission, executor, None, trace)
    accepted = all(item.passed for item in fences)
    result = {
        "mission_id": mission.id,
        "sandbox_id": handle.sandbox_id,
        "action": action,
        "accepted": accepted,
        "fences": [item.__dict__ for item in fences],
    }
    (output / "mission-report.json").write_text(
        json.dumps(result, indent=2) + "\n", encoding="utf-8"
    )
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="lda-flow")
    sub = parser.add_subparsers(dest="command", required=True)
    campaign = sub.add_parser("campaign")
    campaign.add_argument("path")
    campaign.add_argument("--dry-run", action="store_true")
    campaign.add_argument("--output", default=".lda-campaign")
    mission = sub.add_parser("mission")
    mission.add_argument("action", choices=("prepare", "build", "verify"))
    mission.add_argument("path")
    mission.add_argument("--output", default=".lda-mission")
    args = parser.parse_args(argv)
    try:
        if args.command == "campaign":
            controller = CampaignController(Campaign.from_yaml(args.path), Path(args.output))
            if args.dry_run:
                _print_dry_run(controller)
                return 0
            print(json.dumps(controller.run(), indent=2))
            return 0
        mission = _load_mission(args.path)
        print(json.dumps(_run_mission_action(args.action, mission, Path(args.output)), indent=2))
        return 0
    except Exception as exc:
        print(f"lda-flow: {exc}", file=sys.stderr)
        return 2
