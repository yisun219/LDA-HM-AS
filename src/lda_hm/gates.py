from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from .artifacts import ArtifactStore
from .types import FlowConfig, FlowState, Phase


@dataclass(frozen=True)
class GateResult:
    name: str
    passed: bool
    reason: str = ""
    terminal_phase: Phase | None = None


@dataclass(frozen=True)
class GateContext:
    workspace: Path
    store: ArtifactStore
    state: FlowState
    config: FlowConfig
    current_branch: str = ""
    worktree_clean: bool = True
    has_unpushed_commits: bool = False
    open_blocking_tasks: tuple[str, ...] = ()
    large_changed_files: tuple[str, ...] = ()


GateCheck = Callable[[GateContext], GateResult]


class GateRunner:
    """Runs the fixed mechanical boundary before semantic review."""

    ORDER = (
        "state_schema",
        "branch_anchor",
        "plan_integrity",
        "open_blocking_tasks",
        "git_status_available",
        "large_changed_files",
        "methodology_phase",
        "git_clean",
        "unpushed_commits",
        "round_summary",
        "round_contract",
        "bitlesson_delta",
        "goal_tracker",
        "max_iterations",
        "finalize_complete",
    )

    def run(self, context: GateContext) -> list[GateResult]:
        results: list[GateResult] = []
        for name in self.ORDER:
            result = getattr(self, f"_{name}")(context)
            results.append(result)
            if not result.passed or result.terminal_phase is not None:
                break
        return results

    @staticmethod
    def _pass(name: str) -> GateResult:
        return GateResult(name=name, passed=True)

    def _state_schema(self, context: GateContext) -> GateResult:
        try:
            FlowState.from_dict(context.state.to_dict())
        except (TypeError, ValueError) as error:
            return GateResult("state_schema", False, str(error), Phase.UNEXPECTED)
        return self._pass("state_schema")

    def _branch_anchor(self, context: GateContext) -> GateResult:
        if context.state.start_branch and (
            context.current_branch != context.state.start_branch
        ):
            return GateResult("branch_anchor", False, "working branch changed")
        return self._pass("branch_anchor")

    def _plan_integrity(self, context: GateContext) -> GateResult:
        if context.state.phase in {Phase.SETUP, Phase.IDEA, Phase.PLAN}:
            return self._pass("plan_integrity")
        if not context.store.plan_is_intact(context.state.plan_hash):
            return GateResult("plan_integrity", False, "sealed plan changed")
        return self._pass("plan_integrity")

    def _open_blocking_tasks(self, context: GateContext) -> GateResult:
        if context.open_blocking_tasks:
            return GateResult(
                "open_blocking_tasks",
                False,
                ", ".join(context.open_blocking_tasks),
            )
        return self._pass("open_blocking_tasks")

    def _git_status_available(self, context: GateContext) -> GateResult:
        if not context.workspace.exists():
            return GateResult("git_status_available", False, "workspace missing")
        return self._pass("git_status_available")

    def _large_changed_files(self, context: GateContext) -> GateResult:
        if context.large_changed_files:
            return GateResult(
                "large_changed_files",
                False,
                ", ".join(context.large_changed_files),
            )
        return self._pass("large_changed_files")

    def _methodology_phase(self, context: GateContext) -> GateResult:
        if context.state.phase is Phase.METHODOLOGY_ANALYSIS:
            report = context.store.root / "methodology-report.md"
            if not report.is_file():
                return GateResult(
                    "methodology_phase", False, "methodology report missing"
                )
        return self._pass("methodology_phase")

    def _git_clean(self, context: GateContext) -> GateResult:
        if context.config.require_clean_worktree and not context.worktree_clean:
            return GateResult("git_clean", False, "worktree is not clean")
        return self._pass("git_clean")

    def _unpushed_commits(self, context: GateContext) -> GateResult:
        if context.config.require_pushed_rounds and context.has_unpushed_commits:
            return GateResult("unpushed_commits", False, "round commits are not pushed")
        return self._pass("unpushed_commits")

    def _round_summary(self, context: GateContext) -> GateResult:
        if context.state.phase not in {
            Phase.IMPLEMENTATION,
            Phase.REGULAR_REVIEW,
            Phase.FULL_ALIGNMENT,
            Phase.DRIFT_RECOVERY,
        }:
            return self._pass("round_summary")
        path = context.store.round_dir(context.state.current_round) / "summary.md"
        if not path.is_file() or not path.read_text(encoding="utf-8").strip():
            return GateResult("round_summary", False, "round summary missing")
        return self._pass("round_summary")

    def _round_contract(self, context: GateContext) -> GateResult:
        if context.state.phase not in {
            Phase.IMPLEMENTATION,
            Phase.REGULAR_REVIEW,
            Phase.FULL_ALIGNMENT,
            Phase.DRIFT_RECOVERY,
        }:
            return self._pass("round_contract")
        path = context.store.round_dir(context.state.current_round) / "contract.md"
        if not path.is_file() or not path.read_text(encoding="utf-8").strip():
            return GateResult("round_contract", False, "round contract missing")
        return self._pass("round_contract")

    def _bitlesson_delta(self, context: GateContext) -> GateResult:
        if context.state.phase not in {
            Phase.IMPLEMENTATION,
            Phase.REGULAR_REVIEW,
            Phase.FULL_ALIGNMENT,
            Phase.DRIFT_RECOVERY,
        }:
            return self._pass("bitlesson_delta")
        path = context.store.round_dir(context.state.current_round) / "bitlesson.json"
        if not path.is_file():
            return GateResult("bitlesson_delta", False, "BitLesson delta missing")
        return self._pass("bitlesson_delta")

    def _goal_tracker(self, context: GateContext) -> GateResult:
        if context.state.phase in {Phase.SETUP, Phase.IDEA, Phase.PLAN}:
            return self._pass("goal_tracker")
        path = context.store.root / "goal-tracker.md"
        if not path.is_file() or not path.read_text(encoding="utf-8").strip():
            return GateResult("goal_tracker", False, "goal tracker missing")
        return self._pass("goal_tracker")

    def _max_iterations(self, context: GateContext) -> GateResult:
        if context.state.current_round >= context.config.max_iterations:
            return GateResult(
                "max_iterations",
                True,
                "iteration limit reached",
                Phase.MAX_ITER,
            )
        return self._pass("max_iterations")

    def _finalize_complete(self, context: GateContext) -> GateResult:
        if context.state.phase is not Phase.FINALIZE:
            return self._pass("finalize_complete")
        summary = context.store.root / "finalize-summary.md"
        if not summary.is_file() or not summary.read_text(encoding="utf-8").strip():
            return GateResult("finalize_complete", False, "finalize summary missing")
        return GateResult(
            "finalize_complete", True, "finalize completed", Phase.METHODOLOGY_ANALYSIS
        )
