from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from lda.argus.supervisor import ArgusSupervisor
from lda.e2b.client import E2BClient
from lda.e2b.gateway import GatewayConfig, SharedGateway
from lda.e2b.preflight import Preflight
from lda.models import WorldState
from lda.research.ingest import ingest
from lda.research.campaign import prepare as prepare_campaign
from lda.research.qualification import QualificationRunner
from lda.research.release import evaluate_canary_release
from lda.state.store import EventStore
from lda.templates import build_templates


def _root(args: argparse.Namespace) -> Path:
    return Path(args.root or ".").resolve()


def _client(args: argparse.Namespace) -> E2BClient:
    fallback = getattr(args, "e2b_template", None)
    return E2BClient(SharedGateway(GatewayConfig.from_env()), fake=bool(getattr(args, "fake_e2b", False)),
                     template_fallback=fallback, allow_agent_stub=bool(getattr(args, "allow_agent_stub", False)))


def _run(args: argparse.Namespace) -> dict:
    root = _root(args)
    client = _client(args)
    preflight = Preflight(client).run(args.run_id)
    if not preflight["passed"]:
        raise RuntimeError("E2B preflight failed: " + json.dumps(preflight["checks"], sort_keys=True))
    if not args.campaign_input:
        raise RuntimeError("--campaign-input is required for a formal campaign")
    campaign = prepare_campaign(args.campaign_input, root)
    controller = client.create({"project": "lda", "run_id": args.run_id, "life_cycle": "bootstrap",
        "mission_id": "campaign-input", "candidate_id": "none", "role": "controller",
        "template": "lda-controller", "lease_id": "controller-" + args.run_id})
    raw = Path(args.campaign_input).read_text(encoding="utf-8")
    client.filesystem_write(controller, campaign.e2b_path, raw)
    if __import__("hashlib").sha256(client.filesystem_read(controller, campaign.e2b_path).encode()).hexdigest() != campaign.sha256:
        client.kill(controller)
        raise RuntimeError("controller E2B campaign input hash mismatch after upload")
    client.filesystem_write(controller, "/workspace/campaign-input/manifest.json", json.dumps(campaign.dump(), sort_keys=True))
    qualification_artifact = root / ".lda" / "artifacts" / "qualification.json"
    qualification_artifact.parent.mkdir(parents=True, exist_ok=True)
    qualification = QualificationRunner(client).run(campaign, args.run_id,
                                                      checkpoint_path=qualification_artifact)
    # Qualification may contain incomplete rows for the whole Top 10.  Only
    # the canary rows authorize execution, and every hard gate must carry an
    # explicit evidence reference.
    qualification["qualification_blockers"] = list(qualification.get("release_blockers", []))
    release = evaluate_canary_release(qualification, campaign.canary)
    qualification.update(release)
    qualification_artifact.write_text(json.dumps(qualification, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    if not release["canary_release_ready"]:
        client.kill(controller)
        raise RuntimeError("Campaign stopped before canary missions; release blockers recorded at " + str(qualification_artifact))
    qualified = release["eligible_packages"]
    campaign_dict = campaign.dump()
    supervisor = ArgusSupervisor.bootstrap(root, args.run_id, client=client,
        packages=qualified, campaign=campaign_dict, qualification=qualification)
    results = supervisor.run()
    client.kill(controller)
    return {"run_id": args.run_id, "cycles": len(results), "converged": not supervisor.world.active,
            "reason": supervisor.world.convergence_signals.get("reason"), "preflight": preflight}


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
    run = sub.add_parser("run"); run.add_argument("--flow", required=True, choices=["argus-humanize"]); run.add_argument("--research-snapshot", default=None); run.add_argument("--run-id", default=None); run.add_argument("--package", action="append", default=[]); run.add_argument("--campaign-input", default=None); run.add_argument("--fake-e2b", action="store_true"); run.add_argument("--e2b-template", default=None); run.add_argument("--allow-agent-stub", action="store_true")
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
            if args.e2b_command == "preflight": out = Preflight(client).run(args.run_id)
            else: out = {"reaped": client.reap(args.run_id), "run_id": args.run_id}
        elif args.command == "template": out = {"built": build_templates(root)}
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
            store = EventStore(root); world = store.load_world(); supervisor = ArgusSupervisor(root, client=_client(args), world=world); out = {"results": supervisor.run()}
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
