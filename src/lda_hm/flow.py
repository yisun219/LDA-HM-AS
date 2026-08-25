from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from .artifacts import ArtifactStore
from .types import (
    FlowConfig,
    FlowState,
    MainlineVerdict,
    Phase,
    ReviewResult,
    TerminalReason,
)


class InvalidTransition(RuntimeError):
    pass


class HumanizeFlow:
    """Durable control plane for the LDA-HM flow."""

    def __init__(
        self,
        workspace: Path,
        config: FlowConfig | None = None,
        *,
        run_id: str | None = None,
        results_root: Path | None = None,
    ) -> None:
        self.workspace = workspace.resolve()
        self.config = config or FlowConfig()
        self.run_id = run_id or datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ")
        self.store = ArtifactStore(
            self.workspace,
            self.run_id,
            results_root=results_root,
        )

        if self.store.state_file.exists():
            self.state = self.store.load_state()
        else:
            self.state = FlowState(run_id=self.run_id)
            self.store.save_state(self.state)

    @classmethod
    def resume(
        cls,
        workspace: Path,
        run_id: str,
        config: FlowConfig | None = None,
        *,
        results_root: Path | None = None,
    ) -> HumanizeFlow:
        return cls(
            workspace,
            config,
            run_id=run_id,
            results_root=results_root,
        )

    def begin(self, task: str) -> None:
        self._require(Phase.SETUP)
        if not task.strip():
            raise ValueError("task must not be empty")
        self.store.write_text("task.md", task.strip() + "\n")
        self._move(Phase.IDEA)

    def record_idea(self, draft: str) -> None:
        self._require(Phase.IDEA)
        if not draft.strip():
            raise ValueError("idea draft must not be empty")
        self.store.write_text("idea.md", draft.rstrip() + "\n")
        self._move(Phase.PLAN)

    def record_plan(
        self,
        plan: str,
        *,
        goal_tracker: str,
        start_branch: str = "",
        base_branch: str = "",
        base_commit: str = "",
    ) -> None:
        self._require(Phase.PLAN)
        if len([line for line in plan.splitlines() if line.strip()]) < 5:
            raise ValueError("plan must contain at least five non-empty lines")
        if not goal_tracker.strip():
            raise ValueError("goal tracker must not be empty")
        self.state.plan_hash = self.store.seal_plan(plan.rstrip() + "\n")
        self.store.write_text("goal-tracker.md", goal_tracker.rstrip() + "\n")
        if start_branch:
            self.state.start_branch = start_branch
        if base_branch:
            self.state.base_branch = base_branch
        if base_commit:
            self.state.base_commit = base_commit
        self._move(Phase.IMPLEMENTATION)

    def begin_round(self, contract: str) -> None:
        self._require(Phase.IMPLEMENTATION, Phase.DRIFT_RECOVERY)
        if not contract.strip():
            raise ValueError("round contract must not be empty")
        round_dir = self.store.round_dir(self.state.current_round)
        self.store.write_text(
            round_dir.relative_to(self.store.root) / "contract.md",
            contract.rstrip() + "\n",
        )
        self._save()

    def finish_builder_round(
        self,
        summary: str,
        *,
        bitlesson_action: str = "none",
        bitlesson_note: str = "",
    ) -> Phase:
        self._require(Phase.IMPLEMENTATION, Phase.DRIFT_RECOVERY)
        if not summary.strip():
            raise ValueError("round summary must not be empty")
        if bitlesson_action not in {"none", "add", "update"}:
            raise ValueError("invalid BitLesson action")
        round_dir = self.store.round_dir(self.state.current_round)
        relative = round_dir.relative_to(self.store.root)
        self.store.write_text(relative / "summary.md", summary.rstrip() + "\n")
        self.store.write_json(
            relative / "bitlesson.json",
            {"action": bitlesson_action, "note": bitlesson_note},
        )
        phase = self._review_phase_for_round(self.state.current_round)
        self._move(phase)
        return phase

    def record_review(self, result: ReviewResult) -> Phase:
        self._require(Phase.REGULAR_REVIEW, Phase.FULL_ALIGNMENT)
        round_dir = self.store.round_dir(self.state.current_round)
        self.store.write_json(
            round_dir.relative_to(self.store.root) / "review.json",
            {
                "verdict": result.verdict.value,
                "complete": result.complete,
                "feedback": result.feedback,
                "blocking_findings": list(result.blocking_findings),
            },
        )
        self.state.last_verdict = result.verdict
        if result.verdict is MainlineVerdict.ADVANCED:
            self.state.stall_count = 0
            self.state.drift_recovery_required = False
        else:
            self.state.stall_count += 1

        if self.state.stall_count >= self.config.circuit_breaker_threshold:
            self.state.terminal_reason = TerminalReason.STOP
            self._move(Phase.STOP)
            return self.state.phase

        if result.complete and not result.blocking_findings:
            self.state.review_started = True
            self._move(Phase.CODE_REVIEW)
            return self.state.phase

        self.state.current_round += 1
        if self.state.current_round >= self.config.max_iterations:
            self.state.terminal_reason = TerminalReason.MAX_ITER
            self._move(Phase.MAX_ITER)
            return self.state.phase

        if self.state.stall_count >= self.config.drift_recovery_threshold:
            self.state.drift_recovery_required = True
            self._move(Phase.DRIFT_RECOVERY)
        else:
            self._move(Phase.IMPLEMENTATION)
        return self.state.phase

    def record_code_review(self, findings: tuple[str, ...]) -> Phase:
        self._require(Phase.CODE_REVIEW)
        self.store.write_json("code-review.json", {"findings": list(findings)})
        if findings:
            self.state.current_round += 1
            self._move(Phase.IMPLEMENTATION)
        else:
            self._move(Phase.FINALIZE)
        return self.state.phase

    def record_finalize(self, summary: str) -> None:
        self._require(Phase.FINALIZE)
        if not summary.strip():
            raise ValueError("finalize summary must not be empty")
        self.store.write_text("finalize-summary.md", summary.rstrip() + "\n")
        self._move(Phase.METHODOLOGY_ANALYSIS)

    def record_methodology(self, report: str) -> None:
        self._require(Phase.METHODOLOGY_ANALYSIS, Phase.MAX_ITER)
        if not report.strip():
            raise ValueError("methodology report must not be empty")
        self.store.write_text("methodology-report.md", report.rstrip() + "\n")
        if self.state.terminal_reason is None:
            self.state.terminal_reason = TerminalReason.COMPLETE
        self._move(Phase.COMPLETE)

    def _review_phase_for_round(self, number: int) -> Phase:
        if (number + 1) % self.config.full_alignment_interval == 0:
            return Phase.FULL_ALIGNMENT
        return Phase.REGULAR_REVIEW

    def _require(self, *phases: Phase) -> None:
        if self.state.phase not in phases:
            allowed = ", ".join(phase.value for phase in phases)
            raise InvalidTransition(
                f"phase {self.state.phase.value} cannot perform this action; expected {allowed}"
            )

    def _move(self, phase: Phase) -> None:
        self.state.phase = phase
        self._save()

    def _save(self) -> None:
        self.store.save_state(self.state)
