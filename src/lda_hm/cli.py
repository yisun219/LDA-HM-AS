from __future__ import annotations

import argparse
import fcntl
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


def _acquire_run_lock(flow: HumanizeFlow):
    """One card, one driver: a second concurrent driver corrupts evidence."""
    lock_path = flow.store.root / ".lda-lock"
    handle = lock_path.open("w")
    try:
        fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError as error:
        handle.close()
        raise RuntimeError(
            f"another lda process already drives run {flow.run_id} ({lock_path})"
        ) from error
    handle.write(str(os.getpid()) + "\n")
    handle.flush()
    return handle


def _read_control(flow: HumanizeFlow) -> dict:
    """Supervision channel: <run>/control.json is re-read at every phase
    boundary so an external supervisor can retarget or abort the run."""
    path = flow.store.root / "control.json"
    if not path.is_file():
        return {}
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return value if isinstance(value, dict) else {}


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
    return E2BSandbox.connect(
        template=os.getenv("E2B_TEMPLATE", template),
        timeout=int(os.getenv("LDA_SANDBOX_TIMEOUT", "14400")),
    )


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
        flow = HumanizeFlow(
            workspace,
            run_id=args.run_id,
            results_root=args.results_root,
        )
        run_lock = _acquire_run_lock(flow)
        sandbox = _connect(card.baseline.template)
        run_identity = {
            "schema_version": 1,
            "run_id": flow.run_id,
            "package": card.package.package,
            "task_card_digest": card.digest(),
            "baseline_digest": card.baseline.digest(),
        }
        run_file = flow.store.root / "run.json"
        if run_file.is_file():
            existing_identity = json.loads(run_file.read_text(encoding="utf-8"))
            if existing_identity != run_identity:
                raise RuntimeError("run identity changed; start a new run ID")
        else:
            flow.store.write_json("run.json", run_identity)
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
        assets_root = Path(__file__).resolve().parents[2] / "sandbox" / "lda-base"
        execution.bootstrap_template_assets(assets_root)
        sandbox.bootstrap_credentials()
        previous_base_commit = flow.state.base_commit
        execution.prepare_workspace()
        if previous_base_commit and flow.state.base_commit != previous_base_commit:
            raise RuntimeError("pinned baseline commit changed; old run cannot be resumed")
        execution.restore_candidate()
        flow.state.metadata["workspace_prepared"] = True
        flow.store.save_state(flow.state)
        if not flow.state.metadata.get("baseline_captured"):
            execution.capture_baseline()
        if flow.state.phase.value == "setup":
            flow.begin(args.task)

        replications = int(os.getenv("LDA_CERT_REPLICATIONS", "2"))
        certifier = None
        if replications > 0:
            def certifier() -> str | None:
                try:
                    execution.certify_candidate(
                        lambda: _connect(card.baseline.template),
                        bootstrap_root=assets_root,
                        replications=replications,
                    )
                    return None
                except Exception as error:
                    return str(error)

        stages = execution.stages(
            certifier=certifier,
            builder_guard=execution.builder_guard,
        )
        if flow.state.phase.value == "idea":
            idea = stages.gen_idea(args.task)
        else:
            idea = flow.store.read_text("idea.md")
        if flow.state.phase.value == "plan":
            stages.gen_plan(idea, max_convergence_rounds=args.max_convergence_rounds)
        execution.sync_control_artifacts()

        from .prompts import SUPERVISOR
        from .supervision import Supervisor

        budget = float(
            os.getenv("LDA_BUDGET_USD", "0")
            or card.metadata.get("budget_usd", 0)
            or 0
        )
        consult = None
        if os.getenv("LDA_SUPERVISOR_LLM", "1") == "1" and topology.has_supervisor:
            consult = lambda _role: topology.fresh_supervisor()  # noqa: E731
        supervisor = Supervisor(
            flow,
            sandbox,
            default_contract=args.contract,
            consult=consult,
            supervisor_prompt=SUPERVISOR,
            budget_usd=budget or None,
            trace_remote_provider=execution.builder_trace_remote,
        )

        while flow.state.phase.value not in {"complete", "stop", "unexpected"}:
            control = _read_control(flow)
            phase = flow.state.phase.value
            if phase in {"implementation", "drift_recovery"}:
                pulse = supervisor.pulse()
                decision = supervisor.decide(pulse, control)
                supervisor.record(pulse, decision)
                print(
                    f"lda: supervisor[{decision.source}] round={flow.state.current_round} "
                    f"action={decision.action} reason={decision.reason[:160]}",
                    file=sys.stderr,
                )
                if decision.action == "abort":
                    flow.supervisor_stop(decision.reason or "supervisor abort")
                    break
                if decision.action == "restart_builder":
                    execution.restart_builder()
                contract = decision.contract or str(control.get("contract") or args.contract)
                stages.review_round(contract=contract)
            else:
                if control.get("action") == "abort":
                    flow.supervisor_stop(str(control.get("reason", "supervisor abort")))
                    break
                if phase in {"regular_review", "full_alignment"}:
                    stages.resume_review()
                elif phase == "code_review":
                    stages.code_review()
                elif phase == "finalize":
                    stages.finalize()
                elif phase in {"methodology_analysis", "max_iter"}:
                    stages.methodology_analysis()
                else:
                    raise RuntimeError(f"unhandled flow phase: {phase}")
        run_lock.close()
        print(json.dumps(flow.state.to_dict(), indent=2, sort_keys=True))
        return 0
    except Exception as error:
        print(f"lda: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
