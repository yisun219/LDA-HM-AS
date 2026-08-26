from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from lda.config.templates import TemplateAliases
from lda.controller.protocol import ControllerProtocol
from lda.e2b.client import E2BClient
from lda.e2b.gateway import GatewayConfig, SharedGateway
from lda.e2b.preflight import Preflight
from lda.research.ingest import ingest
from lda.research.campaign import prepare as prepare_campaign
from lda.state.store import EventStore
from lda.templates import build_templates


def _root(args: argparse.Namespace) -> Path:
    return Path(args.root or ".").resolve()


def _client(args: argparse.Namespace) -> E2BClient:
    fallback = getattr(args, "e2b_template", None)
    return E2BClient(SharedGateway(GatewayConfig.from_env()), fake=bool(getattr(args, "fake_e2b", False)),
                     template_fallback=fallback, allow_agent_stub=bool(getattr(args, "allow_agent_stub", False)))


def _template_aliases(repository_root: Path) -> TemplateAliases:
    configured = os.environ.get("LDA_CONFIG_FILE")
    return TemplateAliases.from_file(configured or repository_root / "configs" / "lda.yaml")


def _run(args: argparse.Namespace) -> dict:
    root = _root(args)
    client = _client(args)
    repository_root = Path(__file__).resolve().parents[3]
    aliases = _template_aliases(repository_root)
    templates = [] if client.fake else build_templates(repository_root, aliases=aliases)
    preflight = Preflight(client, aliases).run(args.run_id)
    if not preflight["passed"]:
        raise RuntimeError("E2B preflight failed: " + json.dumps(preflight["checks"], sort_keys=True))
    if not args.campaign_input:
        raise RuntimeError("--campaign-input is required for a formal campaign")
    campaign = prepare_campaign(args.campaign_input, root)
    protocol = ControllerProtocol(root, client, template_aliases=aliases)
    protocol.prepare(run_id=args.run_id, campaign=campaign.dump(),
                     campaign_content=Path(args.campaign_input).read_bytes())
    result = protocol.start()
    result["preflight"] = preflight
    result["templates"] = templates
    return result


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="lda")
    parser.add_argument("--root", default=".", help=argparse.SUPPRESS)
    sub = parser.add_subparsers(dest="command", required=True)
    e2b = sub.add_parser("e2b"); e2bs = e2b.add_subparsers(dest="e2b_command", required=True)
    q = e2bs.add_parser("preflight"); q.add_argument("--run-id", default="preflight"); q.add_argument("--fake-e2b", action="store_true"); q.add_argument("--e2b-template", default=None)
    q = e2bs.add_parser("reap"); q.add_argument("--run-id", required=True); q.add_argument("--fake-e2b", action="store_true")
    templ = sub.add_parser("template"); ts = templ.add_subparsers(dest="template_command", required=True)
    q = ts.add_parser("build"); q.add_argument("--all", action="store_true")
    research = sub.add_parser("research"); rs = research.add_subparsers(dest="research_command", required=True)
    q = rs.add_parser("ingest"); q.add_argument("paths", nargs="+")
    run = sub.add_parser("run"); run.add_argument("--flow", required=True, choices=["argus-lda", "argus-humanize"]); run.add_argument("--research-snapshot", default=None); run.add_argument("--run-id", default=None); run.add_argument("--package", action="append", default=[]); run.add_argument("--campaign-input", default=None); run.add_argument("--fake-e2b", action="store_true"); run.add_argument("--e2b-template", default=None); run.add_argument("--allow-agent-stub", action="store_true")
    argus = sub.add_parser("argus")
    argus_sub = argus.add_subparsers(dest="argus_command", required=True)
    for name in ("world", "missions", "capabilities"):
        q = argus_sub.add_parser(name); q.add_argument("--run-id", required=True)
    for name in ("status", "logs", "resume", "cancel", "report"):
        q = sub.add_parser(name); q.add_argument("--run-id", required=True); q.add_argument("--fake-e2b", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    root = _root(args)
    try:
        if args.command == "e2b":
            client = _client(args)
            aliases = _template_aliases(Path(__file__).resolve().parents[3])
            if args.e2b_command == "preflight": out = Preflight(client, aliases).run(args.run_id)
            else: out = {"reaped": client.reap(args.run_id), "run_id": args.run_id}
        elif args.command == "template":
            out = {"built": build_templates(root, aliases=_template_aliases(root))}
        elif args.command == "research": out = ingest(args.paths, root)
        elif args.command == "run":
            if not args.run_id:
                import uuid
                args.run_id = "run_" + uuid.uuid4().hex[:16]
            if args.allow_agent_stub:
                os.environ["LDA_ALLOW_AGENT_STUB"] = "1"
            out = _run(args)
        elif args.command in {"status", "logs", "report"}:
            store = EventStore(root); world = store.load_world()
            if args.command == "status": out = world.dump()
            elif args.command == "logs": out = {"events": store.events()}
            else: out = {"run_id": world.run_id, "converged": not world.active, "reason": world.convergence_signals.get("reason"), "outcomes": world.outcome_ledger, "portfolio": world.portfolio_e2e}
        elif args.command == "argus":
            store = EventStore(root); world = store.load_world()
            if args.argus_command == "world": out = world.dump()
            elif args.argus_command == "missions": out = {"missions": [m.__dict__ for m in world.missions]}
            else: out = {"capabilities": [c.__dict__ for c in world.capabilities]}
        elif args.command == "resume":
            out = ControllerProtocol(
                root, _client(args),
                template_aliases=_template_aliases(Path(__file__).resolve().parents[3]),
            ).resume()
        elif args.command == "cancel":
            store = EventStore(root); world = store.load_world(); world.active = False; world.convergence_signals["reason"] = "cancelled_by_user"; store.save_world(world); store.append(world.run_id, str(world.life_cycle), "cli", "CANCEL"); out = {"cancelled": True}
        else:
            raise RuntimeError("unsupported command")
        print(json.dumps(out, indent=2, sort_keys=True, default=str))
        return 0
    except (OSError, ValueError, RuntimeError) as exc:
        print(f"lda: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
