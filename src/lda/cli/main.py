from __future__ import annotations

import argparse
import asyncio
import json
import os
import stat
import sys
import time
import traceback
from pathlib import Path
from uuid import uuid4

import yaml
from e2b import AsyncSandbox
from e2b.sandbox.sandbox_api import SandboxQuery

from lda.artifacts import ArtifactStore
from lda.config import LDAConfig
from lda.controller import PureHumanizeController, RunRequest
from lda.controller.request import MissionDefinition
from lda.e2b.bootstrap import launch_controller, read_run_file, resume_controller
from lda.e2b.preflight import run_preflight
from lda.e2b.pagination import iterate_pages
from lda.e2b.shared_gateway import configure_shared_gateway
from lda.e2b.templates import build_templates
from lda.models import ResearchSnapshot
from lda.packages import InventoryMetrics, freeze_mission_queue
from lda.research import ingest_research


def _template_exists_with_retry(name: str, *, attempts: int = 8) -> bool:
    from e2b import Template

    for attempt in range(attempts):
        try:
            return bool(Template.exists(name))
        except Exception as error:
            message = str(error).lower()
            transient = any(marker in message for marker in ("530", "502", "503", "timeout", "connection"))
            if not transient or attempt == attempts - 1:
                if "530" in message or "1033" in message:
                    raise RuntimeError(
                        "E2B shared gateway is unavailable (HTTP 530/Cloudflare 1033); "
                        "restore the Fact-Lab tunnel before starting a Run"
                    ) from error
                raise RuntimeError(f"E2B template lookup failed for {name}: {error}") from error
            time.sleep(min(2 ** attempt, 10))
    return False


def _root() -> Path:
    return Path(__file__).resolve().parents[3]


def _load_private_environment() -> None:
    yaml_path = Path.home() / ".config" / "lda-hm" / "e2b.yaml"
    if yaml_path.exists():
        if stat.S_IMODE(yaml_path.stat().st_mode) & 0o077:
            raise RuntimeError(f"private E2B YAML must be mode 0600: {yaml_path}")
        private = yaml.safe_load(yaml_path.read_text(encoding="utf-8")) or {}
        api_key = str(private.get("e2b_api_key", ""))
        if api_key:
            os.environ.setdefault("E2B_API_KEY", api_key)
    codex_path = Path.home() / ".config" / "lda-hm" / "codex.yaml"
    if codex_path.exists():
        if stat.S_IMODE(codex_path.stat().st_mode) & 0o077:
            raise RuntimeError(f"private Codex YAML must be mode 0600: {codex_path}")
        provider = yaml.safe_load(codex_path.read_text(encoding="utf-8")) or {}
        for source, target in {
            "codex_base_url": "LDA_CODEX_BASE_URL",
            "codex_api_key": "LDA_CODEX_API_KEY",
            "codex_wire_api": "LDA_CODEX_WIRE_API",
        }.items():
            value = str(provider.get(source, ""))
            if value:
                os.environ.setdefault(target, value)
    path = Path.home() / ".config" / "lda-hm" / "e2b.env"
    if not path.exists():
        return
    if stat.S_IMODE(path.stat().st_mode) & 0o077:
        raise RuntimeError(f"private E2B environment must be mode 0600: {path}")
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.removeprefix("export ").split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def _snapshot(config: LDAConfig, snapshot_id: str) -> ResearchSnapshot:
    artifacts = ArtifactStore(config.artifact_root)
    digest = artifacts.resolve(f"research/{snapshot_id}.json")
    return ResearchSnapshot.model_validate(artifacts.read_json(digest))


def _inventory(path: Path) -> list[InventoryMetrics]:
    value = yaml.safe_load(path.read_text(encoding="utf-8"))
    rows = value.get("packages", value) if isinstance(value, dict) else value
    return [InventoryMetrics.model_validate(item) for item in rows]


def _definitions(path: Path) -> dict[str, MissionDefinition]:
    definitions: dict[str, MissionDefinition] = {}
    for item in sorted(path.glob("*.yaml")):
        definition = MissionDefinition.model_validate(yaml.safe_load(item.read_text(encoding="utf-8")))
        definitions[definition.package] = definition
    return definitions


async def _async_main(args: argparse.Namespace, config: LDAConfig) -> int:
    if args.command == "e2b" and args.e2b_command == "preflight":
        print((await run_preflight(config.e2b, template=args.template)).to_json())
        return 0
    if args.command == "e2b" and args.e2b_command == "reap":
        configure_shared_gateway()
        killed: list[str] = []
        paginator = AsyncSandbox.list(query=SandboxQuery(metadata={"project": "lda", "run_id": args.run_id, "owner": "lda-controller"}))
        async for item in iterate_pages(paginator):
            sandbox_id = str(getattr(item, "sandbox_id", getattr(item, "id", "")))
            if sandbox_id:
                sandbox = await AsyncSandbox.connect(sandbox_id=sandbox_id)
                await sandbox.kill()
                killed.append(sandbox_id)
        print(json.dumps({"run_id": args.run_id, "killed": killed}, indent=2))
        return 0
    if args.command == "run":
        if args.flow != "pure-humanize":
            raise ValueError("only --flow pure-humanize is supported")
        for template in (
            config.e2b.controller_template,
            config.e2b.agent_template,
            config.e2b.base_template,
            config.e2b.judge_template,
            config.e2b.e2e_template,
        ):
            if not _template_exists_with_retry(template):
                build_templates(config, _root())
                break
        snapshot = _snapshot(config, args.research_snapshot)
        request = RunRequest(
            run_id=args.run_id or f"lda-{uuid4().hex}",
            research_snapshot=snapshot,
            inventory=_inventory(args.inventory),
            mission_definitions=_definitions(args.missions),
            queue_limit=args.queue_limit,
            agent_backend=args.agent_backend,
            agent_model=args.model,
            reasoning_effort=args.reasoning_effort,
        )
        launched = await launch_controller(request, config, codex_auth=args.codex_auth)
        print(json.dumps(launched, indent=2, sort_keys=True))
        return 0
    if args.command == "status":
        print(await read_run_file(args.run_id, f"state/runs/{args.run_id}.json"))
        return 0
    if args.command == "logs":
        print(await read_run_file(args.run_id, "state/events.jsonl"), end="")
        return 0
    if args.command == "resume":
        print(json.dumps(await resume_controller(args.run_id, config, codex_auth=args.codex_auth), indent=2))
        return 0
    if args.command == "cancel":
        from lda.e2b.bootstrap import get_volume
        try:
            volume = await get_volume(args.run_id, create=False)
            await volume.write_file("cancel.request", "cancelled\n", force=True)
        except Exception as error:
            from lda.e2b.bootstrap import _find_controller
            if "route not found" not in str(error).lower() and "404" not in str(error):
                raise
            controller = await _find_controller(args.run_id)
            await controller.commands.run("printf cancelled > /opt/lda/persist/cancel.request")
        paginator = AsyncSandbox.list(query=SandboxQuery(metadata={"project": "lda", "run_id": args.run_id}))
        async for item in iterate_pages(paginator):
            sandbox_id = str(getattr(item, "sandbox_id", getattr(item, "id", "")))
            if sandbox_id:
                await (await AsyncSandbox.connect(sandbox_id=sandbox_id)).kill()
        print(json.dumps({"run_id": args.run_id, "cancelled": True}))
        return 0
    if args.command == "report":
        state = json.loads(await read_run_file(args.run_id, f"state/runs/{args.run_id}.json"))
        events = (await read_run_file(args.run_id, "state/events.jsonl")).splitlines()
        report = {
            "run_id": args.run_id,
            "phase": state["phase"],
            "missions": state["missions"],
            "event_count": len(events),
            "release_ready": state["phase"] == "RELEASE_READY",
        }
        print(json.dumps(report, indent=2, sort_keys=True))
        return 0
    if args.command == "controller":
        request = RunRequest.model_validate_json(args.request.read_text(encoding="utf-8"))
        controller = PureHumanizeController(request, config, args.persist_root)
        try:
            state = await controller.run()
        except Exception as error:
            state = controller._load_or_create_state()
            state.failure = f"{type(error).__name__}: {error}"
            controller.store.save_run(state, "run.interrupted", {"error": state.failure})
            raise
        print(state.model_dump_json(indent=2))
        return 0
    raise RuntimeError("unhandled command")


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="lda")
    parser.add_argument("--config", type=Path, default=None)
    sub = parser.add_subparsers(dest="command", required=True)
    e2b = sub.add_parser("e2b")
    e2b_sub = e2b.add_subparsers(dest="e2b_command", required=True)
    preflight = e2b_sub.add_parser("preflight")
    preflight.add_argument("--template", default=None)
    reap = e2b_sub.add_parser("reap")
    reap.add_argument("--run-id", required=True)
    template = sub.add_parser("template")
    template_sub = template.add_subparsers(dest="template_command", required=True)
    build = template_sub.add_parser("build")
    build.add_argument("--all", action="store_true", required=True)
    build.add_argument("--rebuild", action="store_true")
    research = sub.add_parser("research")
    research_sub = research.add_subparsers(dest="research_command", required=True)
    ingest = research_sub.add_parser("ingest")
    ingest.add_argument("paths", type=Path, nargs="+")
    portfolio = sub.add_parser("portfolio")
    portfolio_sub = portfolio.add_subparsers(dest="portfolio_command", required=True)
    plan = portfolio_sub.add_parser("plan")
    plan.add_argument("--research-snapshot", required=True)
    plan.add_argument("--inventory", type=Path, default=Path("configs/package-inventory.yaml"))
    plan.add_argument("--limit", type=int, default=10)
    run = sub.add_parser("run")
    run.add_argument("--flow", required=True)
    run.add_argument("--research-snapshot", required=True)
    run.add_argument("--run-id", default=None)
    run.add_argument("--inventory", type=Path, default=Path("configs/package-inventory.yaml"))
    run.add_argument("--missions", type=Path, default=Path("configs/missions"))
    run.add_argument("--queue-limit", type=int, default=10)
    run.add_argument("--agent-backend", choices=("codex-sdk", "codex-cli"), default="codex-cli")
    run.add_argument("--model", default="gpt-5.6-sol")
    run.add_argument("--reasoning-effort", default="high")
    run.add_argument("--codex-auth", type=Path, default=Path.home() / ".codex" / "auth.json")
    for name in ("status", "logs", "cancel", "report"):
        command = sub.add_parser(name)
        command.add_argument("--run-id", required=True)
    resume = sub.add_parser("resume")
    resume.add_argument("--run-id", required=True)
    resume.add_argument("--codex-auth", type=Path, default=Path.home() / ".codex" / "auth.json")
    controller = sub.add_parser("controller", help="internal E2B Controller entrypoint")
    controller_sub = controller.add_subparsers(dest="controller_command", required=True)
    execute = controller_sub.add_parser("execute")
    execute.add_argument("--request", type=Path, required=True)
    execute.add_argument("--persist-root", type=Path, required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    try:
        _load_private_environment()
        args = _parser().parse_args(argv)
        config = LDAConfig.load(args.config)
        config.e2b.apply_public_environment()
        if args.command == "template":
            built = build_templates(config, _root(), rebuild=args.rebuild)
            print(json.dumps({"built": built}, indent=2))
            return 0
        if args.command == "research":
            snapshot = ingest_research(args.paths, ArtifactStore(config.artifact_root))
            print(snapshot.model_dump_json(indent=2))
            return 0
        if args.command == "portfolio":
            snapshot = _snapshot(config, args.research_snapshot)
            queue = freeze_mission_queue("preview", snapshot, _inventory(args.inventory), limit=args.limit)
            print(queue.model_dump_json(indent=2))
            return 0
        return asyncio.run(_async_main(args, config))
    except Exception as error:
        if os.getenv("LDA_DEBUG_TRACEBACK") == "1":
            traceback.print_exc()
        print(f"lda: {type(error).__name__}: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
