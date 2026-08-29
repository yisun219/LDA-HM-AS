"""External command layer: dynamic supervision of a running LDA flow.

The Supervisor is a flow node, not a bystander. Between rounds it reads the
run's own evidence -- round verdicts, fence failures, benchmark trend, Builder
trace statistics, sandbox resource state, and spend -- plus the human control
file, and emits one auditable decision the driver must obey. During a Builder
turn a watchdog reads the live trace and kills a stalled agent process so a
hung turn surfaces as a failed round instead of a silent hour.

Authority order is fixed: human control > deterministic rules > LLM counsel.
The LLM supervisor is consulted only when something is off-track; its output
is parsed under a strict protocol and any malformed answer degrades to the
deterministic decision.
"""
from __future__ import annotations

import json
import re
import threading
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Callable, Optional

from .flow import HumanizeFlow
from .runtime import Session
from .sandbox import Sandbox
from .types import MainlineVerdict, Phase


SUPERVISOR_ACTIONS = (
    "continue",
    "retarget",
    "restart_builder",
    "abort",
    "grant_grace",
    # Adds an agent for one turn: a fresh independent Analyst reads the run
    # evidence and produces a root-cause diagnosis that is appended to the
    # next Builder contract. Additive and safe, so the LLM may request it too.
    "consult_analyst",
)

_SPEEDUP_SHORTFALL = re.compile(
    r"speedup=(-?[0-9.]+)%\s+required=([0-9.]+)%"
)


@dataclass(frozen=True)
class TraceStats:
    """Deterministic digest of one agent stream-json trace."""

    events: int = 0
    turns: int = 0
    results: int = 0
    tool_uses: int = 0
    errors: int = 0
    total_cost_usd: float = 0.0
    output_tokens: int = 0

    @staticmethod
    def from_lines(lines: Any) -> "TraceStats":
        events = turns = results = tool_uses = errors = output_tokens = 0
        cost = 0.0
        for raw in lines:
            line = raw.strip()
            if not line:
                continue
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                continue
            if not isinstance(event, dict):
                continue
            events += 1
            if event.get("kind") == "turn_start":
                turns += 1
            if event.get("type") == "result":
                results += 1
                cost += float(event.get("total_cost_usd") or 0.0)
                usage = event.get("usage") or {}
                output_tokens += int(usage.get("output_tokens") or 0)
            if event.get("type") == "assistant":
                message = event.get("message") or {}
                for block in message.get("content") or ():
                    if isinstance(block, dict) and block.get("type") == "tool_use":
                        tool_uses += 1
            if event.get("is_error") is True or event.get("subtype") == "error":
                errors += 1
        return TraceStats(
            events=events,
            turns=turns,
            results=results,
            tool_uses=tool_uses,
            errors=errors,
            total_cost_usd=cost,
            output_tokens=output_tokens,
        )


@dataclass(frozen=True)
class RunPulse:
    """Everything the Supervisor is allowed to reason from, all observable."""

    round: int
    phase: str
    stall_count: int
    last_verdict: str
    recent_blocks: tuple[str, ...]
    recent_feedback: tuple[str, ...]
    benchmark_summary: str
    builder_trace: TraceStats
    sandbox_load1: float
    sandbox_disk_avail_gb: float
    spent_usd: float
    budget_usd: Optional[float]

    def to_dict(self) -> dict[str, Any]:
        value = asdict(self)
        value["builder_trace"] = asdict(self.builder_trace)
        return value

    def render(self) -> str:
        lines = [
            f"round: {self.round}",
            f"phase: {self.phase}",
            f"stall_count: {self.stall_count}",
            f"last_verdict: {self.last_verdict or 'none'}",
            f"benchmark: {self.benchmark_summary or 'no paired benchmark yet'}",
            (
                f"builder_trace: turns={self.builder_trace.turns} "
                f"tool_uses={self.builder_trace.tool_uses} "
                f"errors={self.builder_trace.errors} "
                f"cost=${self.builder_trace.total_cost_usd:.2f}"
            ),
            f"sandbox: load1={self.sandbox_load1:.2f} disk_avail={self.sandbox_disk_avail_gb:.1f}G",
            f"spend: ${self.spent_usd:.2f}"
            + (f" of ${self.budget_usd:.2f} budget" if self.budget_usd else " (no budget)"),
        ]
        for index, block in enumerate(self.recent_blocks):
            lines.append(f"recent_block[{index}]: {block[:400]}")
        for index, feedback in enumerate(self.recent_feedback):
            lines.append(f"recent_feedback[{index}]: {feedback[:400]}")
        return "\n".join(lines)


@dataclass(frozen=True)
class SupervisorDecision:
    action: str
    contract: str = ""
    reason: str = ""
    source: str = "rules"

    def __post_init__(self) -> None:
        if self.action not in SUPERVISOR_ACTIONS:
            raise ValueError(f"unknown supervisor action: {self.action}")


def parse_supervisor_answer(text: str) -> SupervisorDecision:
    """Strict ACTION/CONTRACT/REASON protocol; malformed answers raise."""
    action = contract = reason = None
    for raw in text.splitlines():
        line = raw.strip()
        if line.startswith("ACTION:"):
            action = line.partition(":")[2].strip().lower()
        elif line.startswith("CONTRACT:"):
            contract = line.partition(":")[2].strip()
        elif line.startswith("REASON:"):
            reason = line.partition(":")[2].strip()
    if action not in SUPERVISOR_ACTIONS:
        raise ValueError(f"supervisor answer lacks a valid ACTION line: {action!r}")
    if contract is None or reason is None:
        raise ValueError("supervisor answer lacks CONTRACT or REASON")
    if contract.upper() == "NONE":
        contract = ""
    return SupervisorDecision(action=action, contract=contract, reason=reason, source="llm")


class Supervisor:
    """Between-round command node with layered authority."""

    def __init__(
        self,
        flow: HumanizeFlow,
        sandbox: Sandbox,
        *,
        default_contract: str,
        consult: Optional[Callable[[str], Session]] = None,
        supervisor_prompt: str = "",
        budget_usd: Optional[float] = None,
        trace_remote_provider: Optional[Callable[[], str]] = None,
        recent_window: int = 3,
        fresh_analyst: Optional[Callable[[], Session]] = None,
    ) -> None:
        self.flow = flow
        self.sandbox = sandbox
        self.default_contract = default_contract
        self.consult = consult
        self.supervisor_prompt = supervisor_prompt
        self.budget_usd = budget_usd
        self.trace_remote_provider = trace_remote_provider
        self.recent_window = recent_window
        self.fresh_analyst = fresh_analyst
        self.circuit_breaker_threshold = flow.config.circuit_breaker_threshold

    # ------------------------------------------------------------------ pulse

    def pulse(self) -> RunPulse:
        state = self.flow.state
        blocks: list[str] = []
        feedback: list[str] = []
        for number in range(max(0, state.current_round - self.recent_window), state.current_round + 1):
            round_dir = self.flow.store.rounds / str(number)
            blocked = round_dir / "blocked.json"
            review = round_dir / "review.json"
            try:
                if blocked.is_file():
                    value = json.loads(blocked.read_text(encoding="utf-8"))
                    blocks.append(f"round {number} [{value.get('source', '?')}]: {value.get('reason', '')}")
                elif review.is_file():
                    value = json.loads(review.read_text(encoding="utf-8"))
                    verdict = value.get("verdict", "?")
                    findings = "; ".join(value.get("blocking_findings") or ())
                    feedback.append(f"round {number} {verdict}: {findings or 'no blocking findings'}")
            except (OSError, json.JSONDecodeError):
                continue
        for name, label in (
            ("finalize-blocked.json", "finalize [certification]"),
            ("code-review.json", "code review"),
        ):
            path = self.flow.store.root / name
            if not path.is_file():
                continue
            try:
                value = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            round_number = value.get("round")
            if (
                isinstance(round_number, int)
                and round_number >= state.current_round - self.recent_window
            ):
                text = value.get("reason") or "; ".join(value.get("findings") or ())
                if text:
                    feedback.append(f"round {round_number} {label}: {text}")
        return RunPulse(
            round=state.current_round,
            phase=state.phase.value,
            stall_count=state.stall_count,
            last_verdict=state.last_verdict.value if state.last_verdict else "",
            recent_blocks=tuple(blocks[-self.recent_window:]),
            recent_feedback=tuple(feedback[-self.recent_window:]),
            benchmark_summary=self._benchmark_summary(),
            builder_trace=self._builder_trace_stats(),
            sandbox_load1=self._sandbox_load1(),
            sandbox_disk_avail_gb=self._sandbox_disk_avail_gb(),
            spent_usd=self._spent_usd(),
            budget_usd=self.budget_usd,
        )

    def _benchmark_summary(self) -> str:
        path = self.flow.store.root / "benchmark-summary.json"
        if not path.is_file():
            return ""
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return ""
        parts = []
        for entry in value.get("comparisons", ()):
            name = f"{entry.get('layer', '?')}/{entry.get('name', '?')}"
            speedup = entry.get("overall_speedup_percent")
            noise = entry.get("noise_percent")
            if speedup is None:
                continue
            fragment = f"{name}: {speedup:+.2f}% (noise {noise:.2f}%)"
            holdout = entry.get("holdout")
            if isinstance(holdout, dict) and holdout.get("overall_speedup_percent") is not None:
                fragment += f", holdout {holdout['overall_speedup_percent']:+.2f}%"
            per_input = entry.get("per_input") or {}
            ranked = sorted(
                (
                    (name_, values.get("speedup_percent"))
                    for name_, values in per_input.items()
                    if isinstance(values, dict)
                    and values.get("speedup_percent") is not None
                ),
                key=lambda pair: pair[1],
            )
            if len(ranked) > 1:
                fragment += (
                    f", inputs {ranked[0][0]} {ranked[0][1]:+.2f}%"
                    f" .. {ranked[-1][0]} {ranked[-1][1]:+.2f}%"
                )
            if entry.get("verdict_error"):
                fragment += " [failed verdict]"
            parts.append(fragment)
        return "; ".join(parts)

    def _builder_trace_stats(self) -> TraceStats:
        remote = self.trace_remote_provider() if self.trace_remote_provider else ""
        if not remote:
            return TraceStats()
        result = self.sandbox.run(("sh", "-c", f"cat {remote} 2>/dev/null || true"))
        if not result.ok:
            return TraceStats()
        return TraceStats.from_lines(result.stdout.splitlines())

    def _spent_usd(self) -> float:
        result = self.sandbox.run(
            (
                "sh",
                "-c",
                "cat /opt/lda/agent-state/traces/*.jsonl 2>/dev/null | "
                "jq -rs '[.[] | select(.type == \"result\") | .total_cost_usd // 0] | add // 0'",
            )
        )
        if not result.ok:
            return 0.0
        try:
            return float(result.stdout.strip() or "0")
        except ValueError:
            return 0.0

    def _sandbox_load1(self) -> float:
        result = self.sandbox.run(("sh", "-c", "cut -d' ' -f1 /proc/loadavg"))
        try:
            return float(result.stdout.strip()) if result.ok else 0.0
        except ValueError:
            return 0.0

    def _sandbox_disk_avail_gb(self) -> float:
        result = self.sandbox.run(
            ("sh", "-c", "df -BG --output=avail /opt/lda 2>/dev/null | tail -1 | tr -dc 0-9")
        )
        try:
            return float(result.stdout.strip()) if result.ok and result.stdout.strip() else 0.0
        except ValueError:
            return 0.0

    # --------------------------------------------------------------- decision

    def decide(self, pulse: RunPulse, human_control: dict[str, Any]) -> SupervisorDecision:
        human = self._human_decision(human_control)
        if human is not None:
            return human
        rule = self._rule_decision(pulse)
        if rule.action != "continue":
            return rule
        needs_counsel = bool(pulse.recent_blocks) or (
            pulse.last_verdict and pulse.last_verdict != MainlineVerdict.ADVANCED.value
        )
        if needs_counsel and self.consult is not None and self.supervisor_prompt:
            try:
                session = self.consult("supervisor")
                answer = session.ask(
                    self.supervisor_prompt.format(pulse=pulse.render())
                )
                decision = parse_supervisor_answer(str(answer))
                if decision.action == "consult_analyst":
                    # Additive and safe; honor it directly.
                    return decision
                if decision.action in {"abort", "grant_grace"}:
                    # An LLM may recommend but not unilaterally end the run,
                    # and stall forgiveness is a rules-only privilege.
                    return SupervisorDecision(
                        action="retarget",
                        contract=decision.contract or rule.contract,
                        reason=(
                            f"llm recommended {decision.action} (demoted to "
                            f"retarget): {decision.reason}"
                        ),
                        source="llm",
                    )
                return decision
            except Exception as error:  # counsel is advisory; rules are the floor
                return SupervisorDecision(
                    action=rule.action,
                    contract=rule.contract,
                    reason=f"{rule.reason}; llm counsel failed: {error}",
                    source="rules",
                )
        return rule

    def _human_decision(self, control: dict[str, Any]) -> Optional[SupervisorDecision]:
        if not isinstance(control, dict) or not control:
            return None
        action = str(control.get("action", "")).strip().lower()
        contract = str(control.get("contract", "")).strip()
        reason = str(control.get("reason", "human control file")).strip()
        if action == "abort":
            return SupervisorDecision("abort", reason=reason or "human abort", source="human")
        if action == "restart_builder":
            return SupervisorDecision(
                "restart_builder", contract=contract, reason=reason, source="human"
            )
        if contract:
            return SupervisorDecision("retarget", contract=contract, reason=reason, source="human")
        return None

    def _rule_decision(self, pulse: RunPulse) -> SupervisorDecision:
        if pulse.budget_usd is not None and pulse.spent_usd >= pulse.budget_usd:
            return SupervisorDecision(
                "abort",
                reason=f"spend ${pulse.spent_usd:.2f} reached budget ${pulse.budget_usd:.2f}",
            )
        grace = self._near_miss_grace(pulse)
        if grace is not None:
            return grace
        consult = self._drift_consult(pulse)
        if consult is not None:
            return consult
        repeated = self._repeated_block_source(pulse.recent_blocks)
        if repeated:
            return SupervisorDecision(
                "retarget",
                contract=(
                    f"Fix the repeated {repeated} failure before anything else: "
                    f"{pulse.recent_blocks[-1][:300]}. Do not weaken any fence, test, "
                    "or benchmark; make the candidate satisfy it."
                ),
                reason=f"{repeated} blocked two consecutive rounds",
            )
        if (
            pulse.round > 0
            and pulse.recent_blocks
            and pulse.builder_trace.turns == 0
            and pulse.phase in {Phase.IMPLEMENTATION.value, Phase.DRIFT_RECOVERY.value}
        ):
            # A blocked round with an empty trace means the Builder session
            # never actually turned; replace it instead of re-prompting a corpse.
            return SupervisorDecision(
                "restart_builder",
                reason="last round blocked and the builder trace recorded no turns",
            )
        return SupervisorDecision("continue", contract=self.default_contract, reason="on track")

    def _drift_consult(self, pulse: RunPulse) -> Optional[SupervisorDecision]:
        """Entering drift recovery earns one extra agent: a fresh Analyst.

        The same builder session re-reading its own failures tends to repeat
        them; an independent reader diagnosing the block history is the
        cheapest topology change with real value. One consult per stall
        streak, tracked in run metadata.
        """
        if pulse.phase != Phase.DRIFT_RECOVERY.value:
            return None
        last = self.flow.state.metadata.get("last_analyst_consult_round")
        if last is not None and int(last) >= pulse.round - 1:
            return None
        contract = ""
        repeated = self._repeated_block_source(pulse.recent_blocks)
        if repeated:
            contract = (
                f"Fix the repeated {repeated} failure before anything else: "
                f"{pulse.recent_blocks[-1][:300]}. Do not weaken any fence, test, "
                "or benchmark; make the candidate satisfy it."
            )
        return SupervisorDecision(
            "consult_analyst",
            contract=contract,
            reason="drift recovery entered; adding a fresh analyst for an independent diagnosis",
        )

    def consult_analyst(self, pulse: RunPulse) -> str:
        """Run the added Analyst session; returns its diagnosis (or '')."""
        from .prompts import ANALYST_DIAGNOSIS

        if self.fresh_analyst is None:
            return ""
        try:
            session = self.fresh_analyst()
            answer = str(session.ask(ANALYST_DIAGNOSIS.format(pulse=pulse.render())))
        except Exception as error:
            self.flow.store.write_json(
                self.flow.store.round_dir(self.flow.state.current_round).relative_to(
                    self.flow.store.root
                )
                / "diagnosis-failed.json",
                {"error": str(error)},
            )
            return ""
        if not answer.strip():
            return ""
        round_dir = self.flow.store.round_dir(self.flow.state.current_round)
        self.flow.store.write_text(
            round_dir.relative_to(self.flow.store.root) / "diagnosis.md",
            answer.strip() + "\n",
        )
        self.flow.state.metadata["last_analyst_consult_round"] = self.flow.state.current_round
        self.flow.store.save_state(self.flow.state)
        return answer.strip()

    def _near_miss_grace(self, pulse: RunPulse) -> Optional[SupervisorDecision]:
        """An improving speedup near-miss earns one stall forgiveness.

        Conditions, all deterministic: one stall away from the circuit
        breaker; the latest block is a missed speedup target (not a
        regression or a fence); the measured speedup covers at least half the
        requirement; and the previous block was worse (regression, or a
        larger shortfall), so the trajectory is improving.
        """
        if pulse.stall_count + 1 < self.circuit_breaker_threshold:
            return None
        if not pulse.recent_blocks:
            return None
        latest = _SPEEDUP_SHORTFALL.search(pulse.recent_blocks[-1])
        if latest is None or "target not met" not in pulse.recent_blocks[-1]:
            return None
        speedup, required = float(latest.group(1)), float(latest.group(2))
        if required <= 0 or speedup < required / 2.0:
            return None
        improving = True
        if len(pulse.recent_blocks) >= 2:
            previous = _SPEEDUP_SHORTFALL.search(pulse.recent_blocks[-2])
            if previous is not None and "target not met" in pulse.recent_blocks[-2]:
                improving = (required - speedup) < (
                    float(previous.group(2)) - float(previous.group(1))
                )
        if not improving:
            return None
        return SupervisorDecision(
            "grant_grace",
            contract=(
                f"The last candidate reached {speedup:+.2f}% against a "
                f"{required:.2f}% target on the same benchmark - close the "
                f"remaining {required - speedup:.2f}% gap with a further "
                "mechanism on top of the retained work; do not discard it."
            ),
            reason=(
                f"improving near-miss: {speedup:+.2f}% of {required:.2f}% "
                "required; one grace round granted"
            ),
        )

    @staticmethod
    def _repeated_block_source(blocks: tuple[str, ...]) -> str:
        sources = []
        for block in blocks:
            start = block.find("[")
            end = block.find("]", start)
            if 0 <= start < end:
                sources.append(block[start + 1 : end])
        if len(sources) >= 2 and sources[-1] == sources[-2]:
            return sources[-1]
        return ""

    # ----------------------------------------------------------------- record

    def record(self, pulse: RunPulse, decision: SupervisorDecision) -> None:
        round_dir = self.flow.store.round_dir(self.flow.state.current_round)
        self.flow.store.write_json(
            round_dir.relative_to(self.flow.store.root) / "supervision.json",
            {
                "pulse": pulse.to_dict(),
                "decision": asdict(decision),
                "epoch": time.time(),
            },
        )
        self.flow.store.journal(
            "supervision",
            round=self.flow.state.current_round,
            action=decision.action,
            source=decision.source,
            spent_usd=round(pulse.spent_usd, 2),
            builder_turns=pulse.builder_trace.turns,
            builder_tool_uses=pulse.builder_trace.tool_uses,
        )


class BuilderWatchdog:
    """Live supervision of one Builder turn via its growing activity log.

    Polls the total size of the agent-state directory inside the sandbox
    (backend-neutral: claude/codex stream turn files there, pi keeps its
    session log there). When it stops growing for `stall_seconds`, the stall
    is double-confirmed with an immediate re-poll -- a single misread must not
    kill a healthy turn -- and only then is the in-sandbox agent process
    killed, so the turn fails loudly instead of hanging for hours. A watchdog
    that cannot observe (command failures) never kills anything.
    """

    def __init__(
        self,
        sandbox: Sandbox,
        *,
        stall_seconds: int = 900,
        poll_seconds: float = 30.0,
        size_command: tuple[str, ...] = (
            "sh",
            "-c",
            "du -sb /opt/lda/agent-state 2>/dev/null | cut -f1",
        ),
        kill_command: tuple[str, ...] = (
            "sh",
            "-c",
            "pkill -f 'claude|codex|(^| )pi ' || true",
        ),
        mirror_remote: str = "",
        mirror_local: Optional[Path] = None,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.sandbox = sandbox
        self.stall_seconds = stall_seconds
        self.poll_seconds = poll_seconds
        self.size_command = size_command
        self.kill_command = kill_command
        # Live trace custody: each poll snapshots the growing turn file to
        # the host, so an agent that later sanitizes its own trace has
        # already been observed.
        self.mirror_remote = mirror_remote
        self.mirror_local = mirror_local
        self.clock = clock
        self.killed = False
        self.last_size = -1
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None

    def __enter__(self) -> "BuilderWatchdog":
        self._thread = threading.Thread(target=self._watch, daemon=True)
        self._thread.start()
        return self

    def __exit__(self, *exc_info: Any) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=self.poll_seconds * 2)

    def _activity_size(self) -> int:
        result = self.sandbox.run(self.size_command)
        if not result.ok:
            return -1
        try:
            return int(result.stdout.strip() or "-1")
        except ValueError:
            return -1

    def _mirror(self) -> None:
        if not self.mirror_remote or self.mirror_local is None:
            return
        try:
            self.sandbox.get(self.mirror_remote, self.mirror_local)
        except Exception:
            pass

    def _watch(self) -> None:
        last_change = self.clock()
        while not self._stop.wait(self.poll_seconds):
            self._mirror()
            size = self._activity_size()
            if size < 0:
                # Blind watchdogs do not shoot.
                continue
            if size != self.last_size:
                self.last_size = size
                last_change = self.clock()
                continue
            if self.clock() - last_change >= self.stall_seconds:
                confirm = self._activity_size()
                if confirm >= 0 and confirm != self.last_size:
                    self.last_size = confirm
                    last_change = self.clock()
                    continue
                if self._stop.is_set():
                    return
                self.sandbox.run(self.kill_command)
                self.killed = True
                return
