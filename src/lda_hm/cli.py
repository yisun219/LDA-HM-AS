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
    # Cards are created by the checked-in generator; arbitrary Python is never
    # loaded from a card file.
    value = json.loads(path.read_text(encoding="utf-8"))
    from .baseline import BaselineSpec
    from .task_card import BenchmarkSpec, CompatibilityBoundary, Lane, PackagePriority

    value["package"] = PackagePriority(**value["package"])
    value["compatibility"] = CompatibilityBoundary(**value.get("compatibility", {}))
    value["baseline"] = BaselineSpec(**value.get("baseline", {}))
    value["lane"] = Lane(value.get("lane", "mainline"))
    value["micro_benchmarks"] = tuple(BenchmarkSpec(**x) for x in value["micro_benchmarks"])
    value["end_to_end_benchmarks"] = tuple(BenchmarkSpec(**x) for x in value["end_to_end_benchmarks"])
    for name in (
        "setup_commands",
        "baseline_tests",
        "dependency_tests",
        "abi_checks",
        "ffi_checks",
        "behavior_checks",
        "package_lifecycle_checks",
        "security_checks",
        "result_equivalence_checks",
    ):
        value[name] = tuple(tuple(x) for x in value[name])
    return TaskCard(**value)


def _connect(template: str) -> E2BSandbox:
    return E2BSandbox.connect(template=os.getenv("E2B_TEMPLATE", template))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="lda")
    sub = parser.add_subparsers(dest="command", required=True)
    init = sub.add_parser("init-card", help="validate and install a task card")
    init.add_argument("workspace", type=Path)
    init.add_argument("card", type=Path)
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
        if args.command == "init-card":
            card = _card(args.card)
            args.workspace.mkdir(parents=True, exist_ok=True)
            target = args.workspace / ".lda-hm" / "task-card.json"
            target.parent.mkdir(parents=True, exist_ok=True)
            card.write(target)
            print(json.dumps({"card": str(target), "digest": card.digest()}, indent=2))
            return 0

        workspace = args.workspace.resolve()
        card = _card(workspace / ".lda-hm" / "task-card.json")
        sandbox = _connect(card.baseline.template)
        flow = HumanizeFlow(
            workspace,
            run_id=args.run_id,
            results_root=args.results_root,
        )
        flow.store.write_json(
            "run.json",
            {
                "schema_version": 1,
                "run_id": flow.run_id,
                "package": card.package.package,
                "task_card_digest": card.digest(),
                "baseline_digest": card.baseline.digest(),
            },
        )
        agents = {
            role: CommandAgent.from_env(sandbox, role=role)
            for role in ("drafter", "planner", "analyst", "builder", "reviewer")
        }
        from .runtime import SessionTopology

        topology = SessionTopology(cwd=Path("/opt/lda/work"), **agents)
        execution = LDAExecution(
            flow,
            card,
            sandbox,
            topology,
            gate_context_factory=lambda current_flow: LDAExecution.sandbox_gate_context(
                current_flow, sandbox
            ),
        )
        execution.bootstrap_template_assets(Path(__file__).resolve().parents[2] / "sandbox" / "lda-base")
        sandbox.bootstrap_credentials()
        if not flow.state.metadata.get("workspace_prepared"):
            execution.prepare_workspace()
            flow.state.metadata["workspace_prepared"] = True
            flow.store.save_state(flow.state)
        if not flow.state.metadata.get("baseline_captured"):
            execution.capture_baseline()
        if flow.state.phase.value == "setup":
            flow.begin(args.task)
        stages = execution.stages(
            trace_remote="/opt/lda/work/.lda-hm/traces/builder-1.jsonl"
        )
        if flow.state.phase.value == "idea":
            idea = stages.gen_idea(args.task)
        else:
            idea = flow.store.read_text("idea.md")
        if flow.state.phase.value == "plan":
            stages.gen_plan(idea, max_convergence_rounds=args.max_convergence_rounds)
        execution.sync_control_artifacts()
        while flow.state.phase.value not in {"complete", "stop", "max_iter", "unexpected"}:
            if flow.state.phase.value in {"implementation", "drift_recovery"}:
                stages.review_round(contract=args.contract)
            elif flow.state.phase.value == "code_review":
                stages.code_review()
            elif flow.state.phase.value == "finalize":
                flow.record_finalize("Finalize after clean code review")
            elif flow.state.phase.value == "methodology_analysis":
                flow.record_methodology("LDA flow completed with deterministic fences and independent review")
            else:
                raise RuntimeError(f"unhandled flow phase: {flow.state.phase.value}")
        print(json.dumps(flow.state.to_dict(), indent=2, sort_keys=True))
        return 0
    except Exception as error:
        print(f"lda: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
