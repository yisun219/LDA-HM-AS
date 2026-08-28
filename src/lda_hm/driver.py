"""One production run of a package card, from workspace to terminal state.

This is the engine both entry points share: `lda run` drives it with the
in-sandbox harness adapters, and the Humanize 2 flow (`flows/lda`) drives it
with hmz-backed agents. Everything execution-shaped lives here once - E2B
lifecycle, baseline, control artifacts, certification, and the supervised
round loop - so the two entry points cannot drift.
"""
from __future__ import annotations

import fcntl
import json
import os
import sys
from pathlib import Path
from typing import Callable, Optional

from .execution import LDAExecution
from .flow import HumanizeFlow
from .runtime import SessionTopology
from .sandbox import E2BSandbox
from .task_card import TaskCard


def acquire_run_lock(flow: HumanizeFlow):
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


def read_control(flow: HumanizeFlow) -> dict:
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


def load_card(path: Path) -> TaskCard:
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
    value["end_to_end_benchmarks"] = tuple(
        BenchmarkSpec(**x) for x in value["end_to_end_benchmarks"]
    )
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
    value["candidate_build"] = tuple(value.get("candidate_build", ()))
    value["selfcheck_commands"] = tuple(
        tuple(x) for x in value.get("selfcheck_commands", ())
    )
    return TaskCard(**value)


def connect_sandbox(template: str) -> E2BSandbox:
    return E2BSandbox.connect(
        template=os.getenv("E2B_TEMPLATE", template),
        timeout=int(os.getenv("LDA_SANDBOX_TIMEOUT", "14400")),
    )


def drive(
    workspace: Path,
    *,
    run_id: Optional[str],
    results_root: Optional[Path],
    topology_factory: Callable[[E2BSandbox, Path], SessionTopology],
    task: str = "",
    contract: str = "Advance the highest-priority unmet acceptance criterion",
    max_convergence_rounds: int = 3,
    on_sandbox: Optional[Callable[[E2BSandbox], None]] = None,
    log: Callable[[str], None] = lambda line: print(line, file=sys.stderr),
) -> HumanizeFlow:
    workspace = workspace.resolve()
    card = load_card(workspace / ".lda-hm" / "task-card.json")
    if not task.strip():
        task = card.goal
    from .types import FlowConfig

    config = FlowConfig(
        max_iterations=int(os.getenv("LDA_MAX_ITERATIONS", "42")),
        circuit_breaker_threshold=int(os.getenv("LDA_STALL_LIMIT", "3")),
        builder_stall_minutes=int(os.getenv("LDA_BUILDER_STALL_MINUTES", "30")),
    )
    flow = HumanizeFlow(workspace, config, run_id=run_id, results_root=results_root)
    run_lock = acquire_run_lock(flow)
    sandbox = connect_sandbox(card.baseline.template)
    if on_sandbox is not None:
        on_sandbox(sandbox)
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

    topology = topology_factory(sandbox, workspace)
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
        flow.begin(task)

    replications = int(os.getenv("LDA_CERT_REPLICATIONS", "2"))
    certifier = None
    if replications > 0:
        def certifier() -> Optional[str]:
            try:
                execution.certify_candidate(
                    lambda: connect_sandbox(card.baseline.template),
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
        idea = stages.gen_idea(task)
    else:
        idea = flow.store.read_text("idea.md")
    if flow.state.phase.value == "plan":
        stages.gen_plan(idea, max_convergence_rounds=max_convergence_rounds)
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
        default_contract=contract,
        consult=consult,
        supervisor_prompt=SUPERVISOR,
        budget_usd=budget or None,
        trace_remote_provider=execution.builder_trace_remote,
        fresh_analyst=topology.fresh_analyst,
    )

    sandbox_ttl = int(os.getenv("LDA_SANDBOX_TIMEOUT", "14400"))
    while flow.state.phase.value not in {"complete", "stop", "unexpected"}:
        # Re-arm the sandbox deadline every round so a long run is never
        # killed by the connect-time TTL.
        refresh = getattr(sandbox, "refresh_timeout", None)
        if callable(refresh):
            refresh(sandbox_ttl)
        control = read_control(flow)
        phase = flow.state.phase.value
        if phase in {"implementation", "drift_recovery"}:
            pulse = supervisor.pulse()
            decision = supervisor.decide(pulse, control)
            supervisor.record(pulse, decision)
            log(
                f"lda: supervisor[{decision.source}] round={flow.state.current_round} "
                f"action={decision.action} reason={decision.reason[:160]}"
            )
            if decision.action == "abort":
                flow.supervisor_stop(decision.reason or "supervisor abort")
                break
            if decision.action == "restart_builder":
                execution.restart_builder()
            elif decision.action == "grant_grace":
                flow.grant_grace(decision.reason)
            round_contract = decision.contract or str(control.get("contract") or contract)
            if decision.action == "consult_analyst":
                diagnosis = supervisor.consult_analyst(pulse)
                if diagnosis:
                    round_contract += "\n\nIndependent diagnosis (added analyst):\n" + diagnosis
            stages.review_round(contract=round_contract)
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
    return flow
