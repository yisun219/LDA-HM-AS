from __future__ import annotations

import argparse
import json
import os
import shlex
import sys
from pathlib import Path

from .agent_command import CommandAgent
from .execution import LDAExecution
from .flow import HumanizeFlow
from .sandbox import E2BSandbox
from .task_card import TaskCard


def _card(path: Path) -> TaskCard:
    from .driver import load_card

    return load_card(path)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="lda")
    sub = parser.add_subparsers(dest="command", required=True)
    init = sub.add_parser("init-card", help="validate and install a task card")
    init.add_argument("workspace", type=Path)
    init.add_argument("card", type=Path)
    init.add_argument(
        "--allow-unranked",
        action="store_true",
        help="accept a package outside the ranked top-30 / pilot list",
    )
    listing = sub.add_parser("candidates", help="list ranked optimization candidates")
    listing.add_argument("--direction", type=int, default=None)
    trace = sub.add_parser(
        "trace", help="render a run's behavioral timeline from its journal"
    )
    trace.add_argument("run_dir", type=Path, help="a <results-root>/runs/<run-id> directory")
    gen = sub.add_parser(
        "gen-card", help="generate a task card for a ranked candidate package"
    )
    gen.add_argument("package", help="binary package name from the top-30 list")
    gen.add_argument("--out", type=Path, default=None, help="output card path")
    probe = sub.add_parser(
        "explore", help="evidence-based feasibility probe for a ranked package"
    )
    probe.add_argument("package")
    probe.add_argument(
        "--results-root",
        type=Path,
        default=Path(os.environ["LDA_RESULTS_ROOT"])
        if os.getenv("LDA_RESULTS_ROOT")
        else Path("."),
    )
    run = sub.add_parser("run", help="run the full LDA flow in E2B")
    run.add_argument("workspace", type=Path)
    run.add_argument("--run-id", default=None)
    run.add_argument(
        "--results-root",
        type=Path,
        default=Path(os.environ["LDA_RESULTS_ROOT"])
        if os.getenv("LDA_RESULTS_ROOT")
        else None,
        help="durable result repository root; defaults to WORKSPACE/.lda-hm",
    )
    run.add_argument("--task", required=True)
    run.add_argument("--contract", default="Advance the highest-priority unmet acceptance criterion")
    run.add_argument("--max-convergence-rounds", type=int, default=3)
    args = parser.parse_args(argv)

    try:
        if args.command == "trace":
            import datetime

            journal = args.run_dir / "journal.jsonl"
            if not journal.is_file():
                print("no journal.jsonl in", args.run_dir, file=sys.stderr)
                return 2
            rounds: dict[int, dict] = {}
            for line in journal.read_text(encoding="utf-8").splitlines():
                try:
                    event = json.loads(line)
                except json.JSONDecodeError:
                    continue
                stamp = datetime.datetime.fromtimestamp(
                    float(event.get("ts", 0))
                ).strftime("%H:%M:%S")
                kind = event.get("kind", "?")
                if kind == "phase":
                    print(
                        f"{stamp}  r{event.get('round', '?')}  "
                        f"{event.get('from_phase')} -> {event.get('to_phase')}"
                        f"  (stall {event.get('stall')})"
                    )
                elif kind == "supervision":
                    print(
                        f"{stamp}  r{event.get('round', '?')}  指挥[{event.get('source')}] "
                        f"{event.get('action')}  spent=${event.get('spent_usd')}"
                    )
                elif kind == "blocked":
                    print(
                        f"{stamp}  r{event.get('round', '?')}  BLOCKED[{event.get('source')}]"
                        f"{' (infra)' if event.get('infra') else ''}  {event.get('reason', '')[:90]}"
                    )
                elif kind == "review":
                    print(
                        f"{stamp}  r{event.get('round', '?')}  verdict {event.get('verdict')}"
                        f"{' COMPLETE' if event.get('complete') else ''}"
                    )
                elif kind == "builder_round":
                    entry = rounds.setdefault(int(event.get("round", -1)), {})
                    entry.update(event)
                    print(
                        f"{stamp}  r{event.get('round', '?')}  builder: "
                        f"{event.get('turns')} turns, {event.get('tool_uses')} tool uses, "
                        f"{event.get('errors')} errors, ${event.get('cost_usd')} / "
                        f"{event.get('output_tokens')} out-tokens"
                    )
            if rounds:
                print("\nper-round behavior curve (round: tool_uses / cost):")
                for number in sorted(rounds):
                    entry = rounds[number]
                    print(
                        f"  r{number}: {entry.get('tool_uses', 0):4d} tool uses, "
                        f"${entry.get('cost_usd', 0)}"
                    )
            return 0

        if args.command == "gen-card":
            from .cardgen import generate_card

            reference = json.loads(
                (Path(__file__).resolve().parents[2] / "examples" / "libpng-card.json")
                .read_text(encoding="utf-8")
            )
            card_value = generate_card(args.package, reference["baseline"])
            out = args.out or Path(f"examples/{args.package}-card.json")
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_text(
                json.dumps(card_value, indent=2, sort_keys=False) + "\n",
                encoding="utf-8",
            )
            _card(out)  # validate through the real loader before handing it out
            print(json.dumps({"card": str(out)}, indent=2))
            return 0

        if args.command == "explore":
            from .explore import explore

            reference = json.loads(
                (Path(__file__).resolve().parents[2] / "examples" / "libpng-card.json")
                .read_text(encoding="utf-8")
            )
            out = explore(
                args.package,
                args.results_root,
                baseline=reference["baseline"],
                assets_root=Path(__file__).resolve().parents[2] / "sandbox" / "lda-base",
            )
            print(json.dumps({"exploration": str(out)}, indent=2))
            return 0

        if args.command == "candidates":
            from .candidates import load_candidates

            for candidate in load_candidates():
                if args.direction is not None and candidate.direction != args.direction:
                    continue
                print(f"{candidate.score:7.2f}  d{candidate.direction}  {candidate.package}")
            return 0

        if args.command == "init-card":
            card = _card(args.card)
            if not args.allow_unranked:
                from .candidates import is_sanctioned

                if not is_sanctioned(card.package.package):
                    raise RuntimeError(
                        f"package {card.package.package!r} is neither the pilot nor a "
                        "ranked top-30 candidate; pass --allow-unranked to override"
                    )
            args.workspace.mkdir(parents=True, exist_ok=True)
            target = args.workspace / ".lda-hm" / "task-card.json"
            target.parent.mkdir(parents=True, exist_ok=True)
            card.write(target)
            print(json.dumps({"card": str(target), "digest": card.digest()}, indent=2))
            return 0

        workspace = args.workspace.resolve()
        from .driver import drive
        from .runtime import SessionTopology

        def topology_factory(sandbox, _workspace):
            agents = {
                role: CommandAgent.from_env(sandbox, role=role)
                for role in (
                    "drafter",
                    "planner",
                    "analyst",
                    "builder",
                    "reviewer",
                    "supervisor",
                )
            }
            return SessionTopology(cwd=Path("/opt/lda/work"), **agents)

        flow = drive(
            workspace,
            run_id=args.run_id,
            results_root=args.results_root,
            topology_factory=topology_factory,
            task=args.task,
            contract=args.contract,
            max_convergence_rounds=args.max_convergence_rounds,
        )
        print(json.dumps(flow.state.to_dict(), indent=2, sort_keys=True))
        return 0
    except Exception as error:
        print(f"lda: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
