from __future__ import annotations

import re
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


# BitLesson: a per-run knowledge base of hard-won lessons, re-validated
# mechanically every round (a claimed delta must actually exist in the KB, an
# update must reference a real entry). The point is that rounds stop
# rediscovering the same failures.
_BITLESSON_ID = re.compile(r"^BL-[0-9]{8}-[A-Za-z0-9._-]+$")
_BITLESSON_PLACEHOLDER = re.compile(r"^(\[.*\]|<.*>|\.*)$")
BITLESSON_FILE = "bitlesson.md"
_BITLESSON_SEED = """# BitLesson Knowledge Base

One entry per hard-won, re-usable lesson. Entries are appended by rounds via
the BITLESSON protocol and are validated mechanically: an `add` must use a
fresh `BL-YYYYMMDD-slug` id, an `update` must reference an existing entry.
"""


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
        bitlesson_id: str = "",
    ) -> Phase:
        self._require(Phase.IMPLEMENTATION, Phase.DRIFT_RECOVERY)
        if not summary.strip():
            raise ValueError("round summary must not be empty")
        applied = self._apply_bitlesson(bitlesson_action, bitlesson_id, bitlesson_note)
        round_dir = self.store.round_dir(self.state.current_round)
        relative = round_dir.relative_to(self.store.root)
        self.store.write_text(relative / "summary.md", summary.rstrip() + "\n")
        self.store.write_json(relative / "bitlesson.json", applied)
        phase = self._review_phase_for_round(self.state.current_round)
        self._move(phase)
        return phase

    def _bitlesson_kb(self) -> str:
        path = self.store.root / BITLESSON_FILE
        if not path.is_file():
            self.store.write_text(BITLESSON_FILE, _BITLESSON_SEED)
        return (self.store.root / BITLESSON_FILE).read_text(encoding="utf-8")

    def _apply_bitlesson(self, action: str, entry_id: str, note: str) -> dict:
        """Validate a claimed BitLesson delta against the KB and apply it.

        A malformed claim is degraded to `none` with the rejection recorded -
        an evidence property, never a round-blocking failure: the fences judge
        the candidate, the KB only preserves lessons.
        """
        if action not in {"none", "add", "update"}:
            action, entry_id, note = "none", "", f"rejected: invalid action {action!r}"
        kb = self._bitlesson_kb()
        record = {"action": action, "id": entry_id, "note": note}
        if action == "none":
            if entry_id:
                record = {"action": "none", "id": "", "note": "rejected: none carries an id"}
            return record
        if not _BITLESSON_ID.fullmatch(entry_id):
            return {"action": "none", "id": "", "note": f"rejected: bad id {entry_id!r}"}
        if not note.strip() or _BITLESSON_PLACEHOLDER.fullmatch(note.strip()):
            return {"action": "none", "id": "", "note": "rejected: placeholder note"}
        exists = f"## {entry_id}" in kb
        if action == "add" and exists:
            return {"action": "none", "id": "", "note": f"rejected: {entry_id} already exists"}
        if action == "update" and not exists:
            return {"action": "none", "id": "", "note": f"rejected: {entry_id} not in KB"}
        if action == "add":
            addition = f"\n## {entry_id}\n\n{note.strip()}\n"
        else:
            addition = f"\n### update {entry_id} (round {self.state.current_round})\n\n{note.strip()}\n"
        self.store.write_text(BITLESSON_FILE, kb.rstrip() + "\n" + addition)
        return record

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
        self.state.metadata["consecutive_infra_blocks"] = 0
        self.store.journal(
            "review",
            round=self.state.current_round,
            verdict=result.verdict.value,
            complete=result.complete,
            blocking=len(result.blocking_findings),
        )
        if result.verdict is MainlineVerdict.ADVANCED:
            self.state.stall_count = 0
            self.state.drift_recovery_required = False
        else:
            self.state.stall_count += 1

        if self.state.stall_count >= self.config.circuit_breaker_threshold:
            self.state.terminal_reason = TerminalReason.STOP
            self._move(Phase.STOP)
            return self.state.phase

        if (
            result.verdict is MainlineVerdict.ADVANCED
            and result.complete
            and not result.blocking_findings
        ):
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

    def record_blocked_round(self, source: str, reason: str, *, infra: bool = False) -> Phase:
        """Advance after a deterministic block without granting Reviewer access.

        Infrastructure blocks (unstable benchmark host, dead reviewer backend)
        follow the Argus evidence split: they can never count against the
        candidate's idea, so they do not feed the stall/drift counters -- but
        they have their own consecutive-failure circuit breaker so a broken
        environment cannot spin forever.
        """
        self._require(Phase.REGULAR_REVIEW, Phase.FULL_ALIGNMENT)
        if not source.strip() or not reason.strip():
            raise ValueError("blocked round source and reason are required")
        round_dir = self.store.round_dir(self.state.current_round)
        self.store.write_json(
            round_dir.relative_to(self.store.root) / "blocked.json",
            {"source": source, "reason": reason, "infra": infra},
        )
        self.store.journal(
            "blocked",
            round=self.state.current_round,
            source=source,
            infra=infra,
            reason=reason[:200],
        )
        self.state.last_verdict = MainlineVerdict.REGRESSED
        if infra:
            consecutive = int(self.state.metadata.get("consecutive_infra_blocks", 0)) + 1
            self.state.metadata["consecutive_infra_blocks"] = consecutive
            if consecutive >= self.config.circuit_breaker_threshold:
                self.state.terminal_reason = TerminalReason.STOP
                self._move(Phase.STOP)
                return self.state.phase
        else:
            self.state.metadata["consecutive_infra_blocks"] = 0
            self.state.stall_count += 1
            if self.state.stall_count >= self.config.circuit_breaker_threshold:
                self.state.terminal_reason = TerminalReason.STOP
                self._move(Phase.STOP)
                return self.state.phase
        self.state.current_round += 1
        if self.state.current_round >= self.config.max_iterations:
            self.state.terminal_reason = TerminalReason.MAX_ITER
            self._move(Phase.MAX_ITER)
            return self.state.phase
        if not infra and self.state.stall_count >= self.config.drift_recovery_threshold:
            self.state.drift_recovery_required = True
            self._move(Phase.DRIFT_RECOVERY)
        else:
            self._move(Phase.IMPLEMENTATION)
        return self.state.phase

    def record_code_review(self, findings: tuple[str, ...]) -> Phase:
        self._require(Phase.CODE_REVIEW)
        self.store.write_json(
            "code-review.json",
            {"findings": list(findings), "round": self.state.current_round},
        )
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

    def reopen_from_finalize(self, reason: str) -> Phase:
        self._require(Phase.FINALIZE)
        if not reason.strip():
            raise ValueError("finalize block reason is required")
        self.store.write_json(
            "finalize-blocked.json",
            {"reason": reason, "round": self.state.current_round},
        )
        self.state.current_round += 1
        if self.state.current_round >= self.config.max_iterations:
            self.state.terminal_reason = TerminalReason.MAX_ITER
            self._move(Phase.MAX_ITER)
        else:
            self._move(Phase.IMPLEMENTATION)
        return self.state.phase

    def grant_grace(self, reason: str) -> bool:
        """One-per-run stall forgiveness for an improving near-miss.

        The circuit breaker cannot see trajectories; the Supervisor can. A
        round that misses a speedup target by a hair while the measured gap
        is shrinking is progress, not drift. Auditable and usable once.
        """
        if not reason.strip():
            raise ValueError("grace reason is required")
        if self.state.metadata.get("grace_granted"):
            return False
        if self.state.stall_count <= 0:
            return False
        self.state.metadata["grace_granted"] = True
        self.state.stall_count -= 1
        self.state.drift_recovery_required = False
        self.store.write_json(
            "supervisor-grace.json",
            {"reason": reason, "round": self.state.current_round},
        )
        self._save()
        return True

    def supervisor_stop(self, reason: str) -> None:
        """External supervision endpoint: abort a run from any live phase."""
        if not reason.strip():
            raise ValueError("supervisor stop reason is required")
        if self.state.phase in {Phase.COMPLETE, Phase.STOP, Phase.UNEXPECTED}:
            return
        self.store.write_json("supervisor-stop.json", {"reason": reason})
        self.state.terminal_reason = TerminalReason.STOP
        self._move(Phase.STOP)

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
        previous = self.state.phase
        self.state.phase = phase
        self._save()
        self.store.journal(
            "phase",
            from_phase=previous.value,
            to_phase=phase.value,
            round=self.state.current_round,
            stall=self.state.stall_count,
        )

    def _save(self) -> None:
        self.store.save_state(self.state)
