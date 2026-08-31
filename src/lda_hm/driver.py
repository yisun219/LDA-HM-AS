"""One production run of a package card, from workspace to terminal state.

This is the engine both entry points share: `lda run` drives it with the
in-sandbox harness adapters, and the Humanize 2 flow (`flows/lda`) drives it
with hmz-backed agents. Everything execution-shaped lives here once - E2B
lifecycle, baseline, control artifacts, certification, and the supervised
round loop - so the two entry points cannot drift.
"""
from __future__ import annotations

import atexit
import fcntl
import json
import os
import signal
import sys
import time
from pathlib import Path
from typing import Callable, Optional

from .execution import LDAExecution
from .flow import HumanizeFlow, InfrastructureOutage
from .runtime import SessionTopology
from .sandbox import E2BSandbox, SandboxUnavailable
from .task_card import TaskCard

# Sandboxes this process opened and has not released yet. A leaked sandbox
# holds its disk image on the shared E2B host for the whole re-armed TTL, so
# release is wired to every exit path we can observe: the normal return below,
# an unhandled exception, and SIGTERM/SIGINT. SIGKILL cannot be observed from
# here - `tools/e2b/reap-sandboxes.py` is what collects those.
_LIVE_SANDBOXES: list = []
_EXIT_HOOKS_ARMED = False


def release_sandbox(sandbox, *, log: Callable[[str], None] = lambda line: None) -> None:
    """Kill one sandbox and forget it. Safe to call more than once."""
    if sandbox in _LIVE_SANDBOXES:
        _LIVE_SANDBOXES.remove(sandbox)
    close = getattr(sandbox, "close", None)
    if not callable(close):
        return
    try:
        close()
        log(f"lda: released sandbox {getattr(sandbox, 'sandbox_id', '?')}")
    except Exception as error:  # a run must never fail on cleanup
        log(f"lda: sandbox release failed (reaper will collect it): {error}")


def _release_all_sandboxes() -> None:
    for sandbox in list(_LIVE_SANDBOXES):
        release_sandbox(
            sandbox, log=lambda line: print(line, file=sys.stderr)
        )


def _arm_exit_hooks() -> None:
    """Release sandboxes on interpreter exit and on a polite kill."""
    global _EXIT_HOOKS_ARMED
    if _EXIT_HOOKS_ARMED:
        return
    _EXIT_HOOKS_ARMED = True
    atexit.register(_release_all_sandboxes)
    for sig in (signal.SIGTERM, signal.SIGINT):
        try:
            previous = signal.getsignal(sig)

            def handler(signum, frame, _previous=previous):
                _release_all_sandboxes()
                if callable(_previous):
                    _previous(signum, frame)
                else:
                    raise SystemExit(128 + signum)

            signal.signal(sig, handler)
        except (ValueError, OSError):
            pass  # not the main thread; atexit still covers us


def track_sandbox(sandbox):
    """Adopt a sandbox so it is released even if this run dies badly."""
    _arm_exit_hooks()
    if sandbox not in _LIVE_SANDBOXES:
        _LIVE_SANDBOXES.append(sandbox)
    return sandbox


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


def _resolve_template(
    template: str,
    *,
    log: Callable[[str], None],
) -> str:
    """Resolve the sandbox template, refusing a silent divergence from the card.

    The card digest is part of run identity, so certifying against a template the
    card never declared would make the recorded provenance wrong. An override is
    still allowed for template-development runs, but it has to be stated.
    """
    override = os.getenv("E2B_TEMPLATE")
    if not override or override == template:
        return template
    if os.getenv("LDA_ALLOW_TEMPLATE_OVERRIDE") != "1":
        raise SandboxUnavailable(
            f"E2B_TEMPLATE={override!r} contradicts the task card template "
            f"{template!r}; refusing so the run cannot be certified against an "
            "undeclared template. Set LDA_ALLOW_TEMPLATE_OVERRIDE=1 to override."
        )
    log(
        f"lda: WARNING template override in effect: card declares {template!r}, "
        f"running on {override!r} (LDA_ALLOW_TEMPLATE_OVERRIDE=1)"
    )
    return override


def connect_sandbox(
    template: str,
    *,
    log: Callable[[str], None] = lambda line: print(line, file=sys.stderr),
) -> E2BSandbox:
    """Acquire the run sandbox, waiting out gateway outages.

    A dead or 502-ing E2B gateway is an infrastructure fact, never a statement
    about the candidate. Losing an entire card because the control plane blinked
    during bootstrap is the most expensive failure mode this flow has, so the
    bootstrap waits (bounded, logged) instead of exiting.
    """
    resolved = _resolve_template(template, log=log)
    timeout = int(os.getenv("LDA_SANDBOX_TIMEOUT", "14400"))
    budget = int(os.getenv("LDA_GATEWAY_WAIT_SECONDS", "21600"))
    ceiling = int(os.getenv("LDA_GATEWAY_BACKOFF_CAP", "300"))
    deadline = time.monotonic() + budget
    delay = 15.0
    attempt = 0
    while True:
        attempt += 1
        try:
            return E2BSandbox.connect(template=resolved, timeout=timeout)
        except SandboxUnavailable as error:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise SandboxUnavailable(
                    f"E2B gateway unavailable for {budget}s across {attempt} attempts; "
                    f"giving up bootstrap: {error}"
                ) from error
            pause = min(delay, ceiling, max(remaining, 1.0))
            log(
                f"lda: e2b gateway unavailable (attempt {attempt}, "
                f"{int(remaining)}s of wait budget left); retrying in {int(pause)}s: {error}"
            )
            time.sleep(pause)
            delay = min(delay * 2, ceiling)


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
    sandbox = track_sandbox(connect_sandbox(card.baseline.template))
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
                    lambda: track_sandbox(connect_sandbox(card.baseline.template)),
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
    try:
        _round_loop(
            flow, execution, stages, supervisor, sandbox, sandbox_ttl,
            contract=contract, log=log,
        )
    except InfrastructureOutage as outage:
        # Consecutive infrastructure blocks: the state is saved at the next
        # implementation round. Give the platform time to recover, release
        # the sandbox, and let the driver loop resume this exact run.
        pause = int(os.getenv("LDA_INFRA_PAUSE_SECONDS", "900"))
        log(f"lda: infrastructure outage, pausing {pause}s before resuming: {outage}")
        release_sandbox(sandbox, log=log)
        run_lock.close()
        time.sleep(pause)
        raise
    release_sandbox(sandbox, log=log)
    run_lock.close()
    return flow


def _round_loop(
    flow: HumanizeFlow,
    execution: LDAExecution,
    stages,
    supervisor,
    sandbox: E2BSandbox,
    sandbox_ttl: int,
    *,
    contract: str,
    log: Callable[[str], None],
) -> None:
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
