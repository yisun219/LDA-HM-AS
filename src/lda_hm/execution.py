from __future__ import annotations

import hashlib
import os
import random
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from .benchmark import (
    BenchmarkEnvironmentError,
    BenchmarkReport,
    BenchmarkRunner,
    PairedComparison,
    compare_paired,
)
from .fence import FenceResult, FenceSuite, integrity_manifest_command, sha256_file
from .flow import HumanizeFlow
from .gates import GateContext, GateRunner
from .runtime import SessionTopology
from .sandbox import (
    TRANSPORT_EXIT_CODE,
    Sandbox,
    SandboxUnavailable,
    sandbox_manifest,
)
from .stages import HumanizeStages
from .task_card import BenchmarkSpec, TaskCard

# EX_TEMPFAIL: a setup check signalling that an upstream package source,
# not the candidate, is what failed.
_EX_TEMPFAIL = 75


# Paths a candidate patch must never touch: changing tests to pass tests is
# the cheapest cheat, so it is blocked mechanically, not by review.
_TEST_PATH_PATTERNS = (
    re.compile(r"^tests/"),
    re.compile(r"/tests/"),
    re.compile(r"^testsuite/"),
    re.compile(r"/testsuite/"),
    re.compile(r"^debian/tests(/|$)"),
    re.compile(r"^contrib/libtests/"),
    re.compile(r"^contrib/testtools/"),
    re.compile(r"^contrib/oss-fuzz/"),
    re.compile(r"(^|/)(pngtest|pngvalid|pngstest|pngunknown|pngimage|timepng)\.c$"),
)


def _setup_timeout() -> int:
    """Per-command ceiling for source setup and candidate package builds.

    The default fits the pilot libraries; heavyweight cards (gtk4 builds its
    whole test suite under the reference policy) raise it via
    LDA_SETUP_TIMEOUT without touching any judged benchmark timeout.
    """
    return int(os.getenv("LDA_SETUP_TIMEOUT", "3600"))
_TEST_TAMPER_LINE_PATTERNS = (
    re.compile(r"nocheck", re.IGNORECASE),
    re.compile(r"override_dh_auto_test", re.IGNORECASE),
)


def scan_candidate_patch_text(patch_text: str) -> list[str]:
    """Return violations that disqualify a candidate patch before review."""
    violations: list[str] = []
    for line in patch_text.splitlines():
        if line.startswith("diff --git "):
            parts = line.split()
            if len(parts) >= 4 and parts[-1].startswith("b/"):
                path = parts[-1][2:]
                for pattern in _TEST_PATH_PATTERNS:
                    if pattern.search(path):
                        violations.append(f"patch modifies test path {path}")
                        break
        elif line.startswith("+") and not line.startswith("+++"):
            for pattern in _TEST_TAMPER_LINE_PATTERNS:
                if pattern.search(line):
                    violations.append(
                        f"patch adds a test-weakening line: {line.strip()[:120]}"
                    )
                    break
    return violations


# A sample that lost more than this fraction of its CPU time to co-tenants is
# evidence about the host, not the candidate.
MAX_STEAL_FRACTION = 0.10


# An A-A calibration run whose apparent effect exceeds this fraction of the
# target it is calibrating for cannot certify that target: the instrument is
# manufacturing more signal than the effect being claimed.
NULL_RUN_BIAS_FRACTION = 0.5


def judge_null_run(
    spec: BenchmarkSpec,
    comparison: PairedComparison,
    min_speedup_percent: float | None,
    *,
    stage: str,
) -> None:
    """Falsify the instrument before trusting it on the candidate.

    This comparison measured the baseline against itself, so the true
    effect is exactly zero by construction. Two ways it can fail. A CI
    that excludes 1.0 means the harness certifies a difference that does
    not exist - a false-positive generator, and no candidate verdict from
    it is worth anything. An apparent effect that is large next to the
    target means the noise floor sits too close to the thing being
    claimed to tell them apart.
    """
    if min_speedup_percent is None:
        return
    apparent = abs(comparison.overall_speedup_percent)
    if comparison.repetitions >= 3 and (
        comparison.ratio_ci95_upper < 1.0 or comparison.ratio_ci95_lower > 1.0
    ):
        raise BenchmarkEnvironmentError(
            f"null run certified a phantom effect [{stage}] "
            f"{spec.layer}/{spec.name}: baseline against itself resolved "
            f"{comparison.overall_speedup_percent:+.3f}% with ratio "
            f"CI95=[{comparison.ratio_ci95_lower:.4f}, "
            f"{comparison.ratio_ci95_upper:.4f}] excluding 1.0; the harness "
            "is a false-positive generator on this host and cannot certify "
            "a candidate"
        )
    budget = NULL_RUN_BIAS_FRACTION * min_speedup_percent
    if apparent > budget:
        raise BenchmarkEnvironmentError(
            f"null run bias too large [{stage}] {spec.layer}/{spec.name}: "
            f"baseline against itself shows {apparent:.3f}% apparent effect "
            f"(budget {budget:.3f}% = half the {min_speedup_percent:.3f}% "
            "target); measure on a quieter host or raise repetitions "
            "before judging the candidate"
        )

def judge_comparison(
    spec: BenchmarkSpec,
    comparison: PairedComparison,
    min_speedup_percent: float | None,
    *,
    stage: str,
) -> None:
    """Apply the deterministic verdict policy to one paired comparison.

    A regression on any input is a veto. A speedup claim must clear the
    declared target, the same-run half-range noise, and a 95% Student-t
    interval on the per-repetition log ratios: an effect the measured
    uncertainty can explain is "indeterminate", which blocks review rather
    than passing it. Excess CPU steal invalidates the run itself.
    """
    if comparison.max_steal_fraction > MAX_STEAL_FRACTION:
        raise BenchmarkEnvironmentError(
            f"benchmark environment unstable [{stage}] {spec.layer}/{spec.name}: "
            f"co-tenant CPU steal reached {comparison.max_steal_fraction * 100.0:.1f}% "
            f"of a sample (limit {MAX_STEAL_FRACTION * 100.0:.0f}%); "
            "rerun the paired benchmark instead of judging the candidate"
        )
    limit = 1.0 + spec.max_regression_percent / 100.0
    for name, entry in sorted(comparison.per_input.items()):
        if entry.ratio_of_medians > limit:
            raise RuntimeError(
                f"benchmark regression [{stage}] {spec.layer}/{spec.name}:{name}: "
                f"candidate {entry.candidate_median_seconds:.6f}s vs baseline "
                f"{entry.baseline_median_seconds:.6f}s "
                f"({-entry.speedup_percent:.3f}% slower, limit {spec.max_regression_percent}%)"
            )
    if min_speedup_percent is None:
        return
    speedup = comparison.overall_speedup_percent
    noise = comparison.noise_percent
    # A pathological window is evidence about the host, never about the
    # candidate: refusing to judge in a co-tenant storm does not lower the
    # bar - the target must still be met on a sane window.
    storm = max(3.0 * min_speedup_percent, 6.0)
    if noise > storm or comparison.baseline_drift_percent > 2.0 * storm:
        raise BenchmarkEnvironmentError(
            f"benchmark window pathological [{stage}] {spec.layer}/{spec.name}: "
            f"half-range={noise:.3f}% drift={comparison.baseline_drift_percent:.3f}% "
            f"against a {min_speedup_percent:.3f}% target; rerun the paired "
            "benchmark on a quieter window instead of judging the candidate"
        )
    if speedup < min_speedup_percent:
        raise RuntimeError(
            f"benchmark speedup target not met [{stage}] {spec.layer}/{spec.name}: "
            f"speedup={speedup:.3f}% required={min_speedup_percent:.3f}% "
            f"(noise={noise:.3f}%, drift={comparison.baseline_drift_percent:.3f}%)"
        )
    # Certification rests on the paired Student-t interval: each repetition's
    # ratio is formed inside one short window (order-alternated), so host
    # drift between windows cancels and the CI is the honest uncertainty.
    # The half-range is reported as a diagnostic, not used as a veto - it is
    # dominated by the two worst repetitions and rejects effects the interval
    # properly certifies.
    if comparison.repetitions < 3 or comparison.ratio_ci95_upper >= 1.0:
        # A spread wildly out of proportion to the effect being judged is
        # evidence about the host (a co-tenant burst hit one repetition),
        # not about the candidate: rerun instead of blaming either side.
        if speedup >= min_speedup_percent and noise > max(
            3.0 * min_speedup_percent, 6.0
        ):
            raise BenchmarkEnvironmentError(
                f"benchmark spread implausible [{stage}] {spec.layer}/{spec.name}: "
                f"half-range={noise:.3f}% against a {min_speedup_percent:.3f}% target "
                f"(speedup={speedup:.3f}%); rerun the paired benchmark on a quieter host"
            )
        raise RuntimeError(
            f"benchmark speedup not certifiable [{stage}] {spec.layer}/{spec.name}: "
            f"speedup={speedup:.3f}% is within measurement noise "
            f"(ratio CI95=[{comparison.ratio_ci95_lower:.4f}, "
            f"{comparison.ratio_ci95_upper:.4f}] includes 1.0, "
            f"half-range={noise:.3f}%, reps={comparison.repetitions}); "
            "increase repetitions or reduce noise before claiming this gain"
        )


def holdout_setup_command(spec: BenchmarkSpec, directory: str, seed: int) -> tuple[str, ...]:
    return tuple(
        part.replace("{dir}", directory).replace("{seed}", str(seed))
        for part in spec.holdout_setup
    )


def paired_with_retry(
    runner: BenchmarkRunner,
    spec: BenchmarkSpec,
    *,
    stage: str,
    envs: dict[str, str] | None = None,
    min_speedup_override: float | None = None,
    on_comparison: Callable[
        [BenchmarkReport, BenchmarkReport, PairedComparison], None
    ] | None = None,
) -> tuple[BenchmarkReport, BenchmarkReport, PairedComparison]:
    """Run one paired benchmark; an unstable environment earns one retry.

    `on_comparison` fires as soon as the paired measurement exists, BEFORE the
    verdict: a failing round must still leave its full per-input breakdown as
    durable evidence, or the Supervisor and Analyst steer blind.
    """
    minimum = (
        min_speedup_override
        if min_speedup_override is not None
        else spec.min_speedup_percent
    )
    last_environment_error: BenchmarkEnvironmentError | None = None
    for attempt in range(2):
        baseline, candidate = runner.run_paired(spec, envs=envs)
        if not baseline.successful or not candidate.successful:
            observations = [
                observation
                for report in (baseline, candidate)
                for observation in report.observations
            ]
            exit_codes = {observation.exit_code for observation in observations}
            if 125 in exit_codes:
                raise BenchmarkEnvironmentError(
                    f"sandbox transport died during paired benchmark "
                    f"{spec.layer}/{spec.name} (exit=125)"
                )
            raise RuntimeError(
                f"paired benchmark failed: {spec.layer}/{spec.name}: "
                f"exits={sorted(exit_codes)}: "
                + (candidate.observations[-1].stderr_tail if candidate.observations else "")[-500:]
            )
        comparison = compare_paired(spec, baseline, candidate)
        if on_comparison is not None:
            on_comparison(baseline, candidate, comparison)
        try:
            judge_comparison(spec, comparison, minimum, stage=stage)
        except BenchmarkEnvironmentError as error:
            last_environment_error = error
            if attempt == 0:
                continue
            raise
        return baseline, candidate, comparison
    raise last_environment_error  # pragma: no cover - loop always returns or raises


@dataclass
class LDAExecution:
    """The production orchestration boundary for one package task card."""

    flow: HumanizeFlow
    card: TaskCard
    sandbox: Sandbox
    topology: SessionTopology
    gate_context_factory: Callable[[HumanizeFlow], GateContext] | None = None
    require_e2b: bool = True

    def __post_init__(self) -> None:
        if self.require_e2b and self.sandbox.sandbox_id.startswith("fake-"):
            # Fake sandboxes are valid only for tests; a production execution
            # must carry an E2B identity.
            raise SandboxUnavailable("production LDA execution requires an E2B sandbox")
        self.flow.state.metadata["sandbox"] = sandbox_manifest(
            self.card.baseline.template,
            self.sandbox.sandbox_id,
        )
        self.flow.state.metadata["task_card_digest"] = self.card.digest()
        self.flow.store.write_json("task-card.json", self.card.canonical())
        self.flow.store.save_state(self.flow.state)

    def stages(
        self,
        *,
        trace_file: Path | None = None,
        trace_remote: str | None = None,
        certifier: Callable[[], str | None] | None = None,
        builder_guard: Callable[[], object] | None = None,
    ) -> HumanizeStages:
        provider = None
        if trace_remote is None and trace_file is None:
            provider = self.builder_trace_remote
        suite = FenceSuite(
            self.sandbox,
            self.card,
            trace_file=trace_file,
            trace_remote=trace_remote,
            trace_remote_provider=provider,
            integrity_manifest=self._stored_integrity_manifest(),
        )
        runner = GateRunner()
        return HumanizeStages(
            self.flow,
            self.topology,
            fence_suite=suite,
            gate_runner=runner,
            gate_context_factory=self.gate_context_factory,
            pre_review_hook=self.run_candidate_benchmarks,
            builder_guard=builder_guard,
            certifier=certifier,
        )

    def builder_session_name(self) -> str:
        name = self.topology.builder_session_id() if self.topology else "builder-1"
        self.flow.state.metadata["builder_session"] = name
        return name

    def builder_trace_remote(self) -> str:
        return f"/opt/lda/agent-state/traces/{self.builder_session_name()}.jsonl"

    def builder_guard(self):
        """Live watchdog over one Builder turn (imported lazily to avoid cycles).

        The watchdog gets its own connection to the sandbox when the adapter
        supports it: the main thread is blocked inside the agent command for
        up to an hour, and a shared client would leave the watchdog blind.
        It also mirrors the live turn trace to the host so the Builder cannot
        quietly rewrite its own history before checkpoint.
        """
        from .supervision import BuilderWatchdog

        watch_sandbox = self.sandbox
        sibling = getattr(self.sandbox, "sibling", None)
        if callable(sibling):
            try:
                candidate_watch = sibling()
                if candidate_watch.run(("true",)).ok:
                    watch_sandbox = candidate_watch
            except Exception:
                watch_sandbox = self.sandbox
        session = self.builder_session_name()
        return BuilderWatchdog(
            watch_sandbox,
            stall_seconds=self.flow.config.builder_stall_minutes * 60,
            mirror_remote=f"/opt/lda/agent-state/traces/{session}.turn.jsonl",
            mirror_local=self.flow.store.root / "raw-traces" / f"live-{session}.turn.jsonl",
        )

    def restart_builder(self) -> str:
        """Replace a poisoned or dead Builder session and re-anchor traces."""
        name = self.topology.restart_builder()
        self.flow.state.metadata["builder_session"] = name
        self.flow.store.save_state(self.flow.state)
        return name

    def bootstrap_template_assets(self, root: Path) -> None:
        """Install the run's pinned harness into this E2B sandbox.

        The first setup snapshots the checked-in assets into the run
        directory; every later bootstrap (resume, requeue, certification)
        installs from that snapshot. A run is therefore immune to repository
        evolution: new check scripts landing for the next card cannot change
        this run's integrity-pinned content mid-flight.
        """
        bootstrap = getattr(self.sandbox, "bootstrap_assets", None)
        if bootstrap is None:
            raise SandboxUnavailable("sandbox does not support E2B asset bootstrap")
        snapshot = self.flow.store.root / "assets-snapshot"
        if not snapshot.is_dir():
            import shutil

            staging = snapshot.with_name("assets-snapshot.partial")
            if staging.exists():
                shutil.rmtree(staging)
            shutil.copytree(root, staging)
            staging.replace(snapshot)
        bootstrap(snapshot)

    def prepare_workspace(self, *, target_workspace: str = "/opt/lda/work") -> None:
        release = self.sandbox.run(("sh", "-c", ". /etc/os-release && printf %s \"$VERSION_ID\""))
        if not release.ok or release.stdout.strip() != "26.04":
            raise SandboxUnavailable("lda-base must run Ubuntu 26.04")
        # The target CPU (card metadata, e.g. Xeon Gold 6548Y+) is an
        # optimization TARGET for architecture-specific work, not an
        # admission gate: benchmarks are self-paired on whatever host the
        # sandbox landed on, so heterogeneous placement cannot corrupt a
        # verdict. The actual model is recorded for attribution.
        cpu = self.sandbox.run(
            ("sh", "-c", "lscpu | sed -n 's/^Model name:[[:space:]]*//p'; lscpu | sed -n 's/^Model:[[:space:]]*//p'")
        )
        self.flow.state.metadata["sandbox_cpu"] = (
            " ".join(cpu.stdout.split()) if cpu.ok else "unknown"
        )
        baseline_check = self.sandbox.run(self.card.baseline.verification_command(), timeout_seconds=600)
        if not baseline_check.ok:
            raise SandboxUnavailable(
                "baseline identity verification failed: " + baseline_check.stderr[-1200:]
            )
        self.flow.state.metadata["baseline"] = self.card.baseline.canonical()
        self.flow.state.metadata["baseline_digest"] = self.card.baseline.digest()
        self.flow.state.metadata["baseline_verified"] = True
        self.flow.store.write_json("baseline.json", self.card.baseline.canonical())
        for command in self.card.setup_commands:
            result = self.sandbox.run(
                ("env", *self._baseline_env(), *command),
                timeout_seconds=_setup_timeout(),
            )
            if not result.ok:
                # EX_TEMPFAIL from a setup check means an upstream package
                # source is down (Canonical's snapshot service, the release
                # archive). That is an infrastructure fact: the run pauses and
                # resumes later, rather than ending as if the candidate were at
                # fault. Any other non-zero exit is a real setup defect.
                if result.exit_code == _EX_TEMPFAIL:
                    raise SandboxUnavailable(
                        f"package source outage during setup: {command}: "
                        + result.stderr[-800:]
                    )
                raise RuntimeError(f"source setup failed: {command}: {result.stderr[-1000:]}")
        selfcheck_records = []
        selfcheck_commands = [("/opt/lda/harness/checks/fence-selfcheck.sh",)]
        selfcheck_commands += [tuple(c) for c in self.card.selfcheck_commands]
        for command in selfcheck_commands:
            selfcheck = self.sandbox.run(tuple(command), timeout_seconds=1800)
            selfcheck_records.append(
                {
                    "command": list(command),
                    "passed": selfcheck.ok,
                    "stdout": selfcheck.stdout[-4000:],
                    "stderr": selfcheck.stderr[-2000:],
                }
            )
            if not selfcheck.ok:
                break
        self.flow.store.write_json(
            "fence-selfcheck.json", {"checks": selfcheck_records}
        )
        if not all(record["passed"] for record in selfcheck_records):
            raise SandboxUnavailable(
                "fence self-check failed; checkers are not trustworthy: "
                + selfcheck_records[-1]["stderr"][-800:]
            )
        self._seal_pinned_directories()
        self._pin_integrity_manifest()
        branch = self.sandbox.run(("git", "-C", target_workspace, "branch", "--show-current"))
        commit = self.sandbox.run(("git", "-C", target_workspace, "rev-parse", "HEAD"))
        if not branch.ok or not commit.ok:
            raise RuntimeError("prepared target workspace must be a Git repository")
        self.flow.state.start_branch = branch.stdout.strip()
        self.flow.state.base_branch = branch.stdout.strip()
        self.flow.state.base_commit = commit.stdout.strip()
        self.flow.state.metadata["source_reference"] = self.card.source_reference
        self.flow.store.save_state(self.flow.state)

    def _seal_pinned_directories(self) -> None:
        """Root-seal checkers and fixtures once setup has produced them.

        The Builder has sandbox sudo, so sealing alone is a speed bump; the
        digest manifest below is the actual tripwire and fresh-sandbox
        certification is the hard guarantee.
        """
        paths = " ".join(self.card.integrity_paths)
        sealed = self.sandbox.run(
            (
                "sudo",
                "-n",
                "sh",
                "-c",
                f"chown -R root:root {paths} && "
                f"find {paths} -type f -exec chmod a-w {{}} + && "
                f"find {paths} -type d -exec chmod a-w {{}} +",
            )
        )
        if not sealed.ok:
            raise RuntimeError(
                "could not seal pinned directories: " + sealed.stderr[-500:]
            )

    def _pin_integrity_manifest(self) -> str:
        result = self.sandbox.run(
            integrity_manifest_command(self.card.integrity_paths),
            timeout_seconds=900,
        )
        if not result.ok or not result.stdout.strip():
            raise RuntimeError(
                "could not compute integrity manifest: " + result.stderr[-500:]
            )
        manifest = result.stdout.strip() + "\n"
        stored = self._stored_integrity_manifest()
        if stored is None:
            self.flow.store.write_text("integrity-manifest.sha256", manifest)
        elif stored.strip() != manifest.strip():
            raise RuntimeError(
                "pinned directory content differs from the recorded manifest; "
                "the baseline of this run is no longer reproducible"
            )
        return manifest

    def _stored_integrity_manifest(self) -> str | None:
        path = self.flow.store.root / "integrity-manifest.sha256"
        if not path.is_file():
            return None
        return path.read_text(encoding="utf-8")

    def verify_integrity(self) -> None:
        stored = self._stored_integrity_manifest()
        if stored is None:
            raise RuntimeError("integrity manifest was never pinned for this run")
        result = self.sandbox.run(
            integrity_manifest_command(self.card.integrity_paths),
            timeout_seconds=900,
        )
        if not result.ok:
            if result.exit_code == TRANSPORT_EXIT_CODE:
                raise SandboxUnavailable(
                    "integrity sweep could not reach the sandbox: "
                    + result.stderr[-500:]
                )
            raise RuntimeError("integrity sweep failed: " + result.stderr[-500:])
        if result.stdout.strip() != stored.strip():
            raise RuntimeError(
                "pinned harness/baseline/fixture content changed since setup; "
                "benchmark and fence verdicts would be meaningless"
            )

    def restore_candidate(self, *, target_workspace: str = "/opt/lda/work") -> None:
        """Rehydrate the latest durable candidate into a newly created Sandbox."""
        patch = self.flow.store.root / "candidate.patch"
        if patch.is_file() and patch.stat().st_size:
            remote_patch = f"/scratch/lda-hm/{self.flow.run_id}-resume-candidate.patch"
            self.sandbox.put(patch, remote_patch)
            check = self.sandbox.run(
                ("git", "-C", target_workspace, "apply", "--check", remote_patch)
            )
            if not check.ok:
                raise RuntimeError("saved candidate patch no longer applies to the pinned baseline")
            applied = self.sandbox.run(
                ("git", "-C", target_workspace, "apply", "--index", remote_patch)
            )
            if not applied.ok:
                raise RuntimeError("could not restore saved candidate patch")
            committed = self.sandbox.run(
                (
                    "git",
                    "-C",
                    target_workspace,
                    "commit",
                    "-m",
                    f"Restore LDA candidate for {self.flow.run_id}",
                )
            )
            if not committed.ok:
                raise RuntimeError("could not commit restored candidate patch")
        traces_dir = self.flow.store.root / "raw-traces"
        if traces_dir.is_dir():
            for raw_trace in sorted(traces_dir.glob("*.jsonl")):
                if not raw_trace.stat().st_size:
                    continue
                remote_trace = f"/opt/lda/agent-state/traces/{raw_trace.name}"
                prepared = self.sandbox.run(("mkdir", "-p", str(Path(remote_trace).parent)))
                if not prepared.ok:
                    raise RuntimeError("could not prepare restored trace directory")
                self.sandbox.put(raw_trace, remote_trace)
        status = self.sandbox.run(("git", "-C", target_workspace, "status", "--porcelain"))
        if not status.ok or status.stdout.strip():
            raise RuntimeError("restored candidate worktree is not clean")

    def _baseline_env(self) -> tuple[str, ...]:
        baseline = self.card.baseline
        return tuple(
            f"{key}={value}"
            for key, value in {
                "LDA_BASELINE_MODE": baseline.mode,
                "LDA_BASELINE_RELEASE": baseline.release,
                "LDA_BASELINE_CODENAME": baseline.codename,
                "LDA_BASELINE_APT_SNAPSHOT": baseline.apt_snapshot,
            }.items()
        )

    def sync_control_artifacts(self) -> None:
        control = "/opt/lda/control"
        self.sandbox.run(("mkdir", "-p", control))
        files = {
            "task-card.json": self.flow.store.root / "task-card.json",
            "plan.md": self.flow.store.root / "plan.md",
            "goal-tracker.md": self.flow.store.root / "goal-tracker.md",
            "baseline.json": self.flow.store.root / "baseline.json",
        }
        for name, local in files.items():
            if not local.is_file():
                raise FileNotFoundError(local)
            remote = f"{control}/{name}"
            self.sandbox.put(local, remote)
            result = self.sandbox.run(("chmod", "0444", remote))
            if not result.ok:
                raise RuntimeError(f"could not protect control artifact {name}")
        sealed = self.sandbox.run(
            (
                "sudo",
                "-n",
                "sh",
                "-c",
                "chown -R root:root /opt/lda/control && "
                "find /opt/lda/control -type f -exec chmod 0444 {} + && "
                "find /opt/lda/control -type d -exec chmod 0555 {} +",
            )
        )
        if not sealed.ok:
            raise RuntimeError("could not seal immutable control artifacts")

    def capture_baseline(self) -> tuple[BenchmarkReport, ...]:
        if not self.flow.state.metadata.get("baseline_verified"):
            raise SandboxUnavailable("cannot capture benchmarks before baseline verification")
        runner = BenchmarkRunner(self.sandbox)
        reports = [runner.run_baseline(spec) for spec in self.card.micro_benchmarks]
        reports.extend(runner.run_baseline(spec) for spec in self.card.end_to_end_benchmarks)
        for report in reports:
            if not report.successful:
                detail = (
                    report.observations[-1].stderr_tail[-500:]
                    if report.observations
                    else "no observations"
                )
                raise RuntimeError(
                    f"baseline benchmark failed: {report.layer}/{report.name}: {detail}"
                )
            if not report.instrumented:
                raise RuntimeError(
                    f"baseline benchmark is not instrumented: {report.layer}/{report.name} "
                    "emitted no in-sandbox LDA_BENCH samples"
                )
            report.write(self.flow.store.root / "benchmarks" / "baseline" / f"{report.layer}-{report.name}.json")
        self.flow.state.metadata["baseline_captured"] = True
        self.flow.store.save_state(self.flow.state)
        return tuple(reports)

    def run_candidate_benchmarks(self) -> tuple[BenchmarkReport, ...]:
        self.verify_integrity()
        self._checkpoint_candidate()
        self._scan_candidate_patch()
        build_command = tuple(self.card.candidate_build) or (
            "/opt/lda/harness/checks/ensure-libpng-candidate.sh",
        )
        prepared = self.sandbox.run(build_command, timeout_seconds=_setup_timeout())
        if not prepared.ok:
            raise RuntimeError(
                "candidate package build failed before benchmarking: "
                + prepared.stderr[-1200:]
            )
        runner = BenchmarkRunner(self.sandbox)
        reports: list[BenchmarkReport] = []
        specs = (*self.card.micro_benchmarks, *self.card.end_to_end_benchmarks)
        comparisons: list[dict] = []
        paired_dir = self.flow.store.root / "benchmarks" / "paired"

        def flush(verdict_error: str | None = None) -> None:
            payload = {
                "timing_source": "in-sandbox LDA_BENCH samples (host transport excluded)",
                "pairing": "same sandbox, per-repetition alternating order",
                "comparisons": comparisons,
            }
            if verdict_error is not None:
                payload["verdict_error"] = verdict_error
            self.flow.store.write_json("benchmark-summary.json", payload)

        for spec in specs:
            # A blocked verdict must still leave the full per-input breakdown
            # behind: the Supervisor, the Analyst, and the next Builder round
            # localize from these numbers, not from one error sentence.
            pending: dict = {}

            def keep_train(baseline, candidate, comparison, *, _spec=spec, _pending=pending):
                baseline.write(paired_dir / f"{_spec.layer}-{_spec.name}-baseline.json")
                candidate.write(paired_dir / f"{_spec.layer}-{_spec.name}-candidate.json")
                _pending["entry"] = comparison.to_dict() | {
                    "max_regression_percent": _spec.max_regression_percent,
                    "min_speedup_percent": _spec.min_speedup_percent,
                    "certified": _spec.min_speedup_percent is not None,
                }

            def keep_holdout(baseline, candidate, comparison, *, _spec=spec, _pending=pending):
                entry = _pending.get("entry")
                if entry is not None:
                    entry["holdout"] = comparison.to_dict() | {
                        "min_speedup_percent": _spec.holdout_min_speedup_percent,
                    }

            try:
                baseline, candidate, comparison = paired_with_retry(
                    runner, spec, stage="train", on_comparison=keep_train
                )
                if spec.holdout_min_speedup_percent is not None:
                    self._run_holdout(runner, spec, on_comparison=keep_holdout)
            except Exception as error:
                if pending.get("entry") is not None:
                    pending["entry"]["verdict_error"] = str(error)
                    comparisons.append(pending["entry"])
                flush(verdict_error=str(error))
                try:
                    self._publish_review_bundle()
                except Exception:
                    pass  # evidence for the next round, never a second failure
                raise
            comparisons.append(pending["entry"])
            flush()
            reports.extend((baseline, candidate))
        self._publish_review_bundle()
        return tuple(reports)

    def _scan_candidate_patch(self) -> None:
        patch = self.flow.store.root / "candidate.patch"
        if not patch.is_file():
            return
        violations = scan_candidate_patch_text(patch.read_text(encoding="utf-8"))
        if violations:
            raise RuntimeError("test tampering detected: " + "; ".join(violations[:5]))

    def _holdout_seed(self) -> int:
        seed = self.flow.state.metadata.get("holdout_seed")
        if seed is None:
            # Host-held secret: never synced into the sandbox during Builder
            # turns; only its digest is published for pre-registration proof.
            seed = random.SystemRandom().randrange(1, 2**31)
            self.flow.state.metadata["holdout_seed"] = seed
            self.flow.state.metadata["holdout_seed_sha256"] = hashlib.sha256(
                str(seed).encode()
            ).hexdigest()
            self.flow.store.save_state(self.flow.state)
        return int(seed)

    def _run_holdout(
        self,
        runner: BenchmarkRunner,
        spec: BenchmarkSpec,
        *,
        on_comparison=None,
    ) -> PairedComparison:
        seed = self._holdout_seed()
        directory = f"/scratch/lda-hm/holdout-{self.flow.run_id}-r{self.flow.state.current_round}"
        setup = holdout_setup_command(spec, directory, seed)
        prepared = self.sandbox.run(setup, timeout_seconds=600)
        if not prepared.ok:
            raise RuntimeError(
                f"holdout fixture generation failed: {prepared.stderr[-800:]}"
            )
        try:
            baseline, candidate, comparison = paired_with_retry(
                runner,
                spec,
                stage="holdout",
                envs={spec.holdout_env: directory},
                min_speedup_override=spec.holdout_min_speedup_percent,
                on_comparison=on_comparison,
            )
            holdout_dir = self.flow.store.root / "benchmarks" / "holdout"
            baseline.write(holdout_dir / f"{spec.layer}-{spec.name}-baseline.json")
            candidate.write(holdout_dir / f"{spec.layer}-{spec.name}-candidate.json")
            return comparison
        finally:
            self.sandbox.run(("rm", "-rf", directory))

    def _checkpoint_candidate(self) -> None:
        diff = self.sandbox.run(
            (
                "git",
                "-C",
                "/opt/lda/work",
                "diff",
                "--binary",
                f"{self.flow.state.base_commit}..HEAD",
            )
        )
        log = self.sandbox.run(
            (
                "git",
                "-C",
                "/opt/lda/work",
                "log",
                "--oneline",
                "--decorate",
                f"{self.flow.state.base_commit}..HEAD",
            )
        )
        if not diff.ok or not log.ok:
            raise RuntimeError("could not checkpoint candidate source")
        self.flow.store.write_text("candidate.patch", diff.stdout)
        self.flow.store.write_text("candidate-log.txt", log.stdout)
        session = self.builder_session_name()
        raw_trace = self.flow.store.root / "raw-traces" / f"{session}.jsonl"
        self.sandbox.get(self.builder_trace_remote(), raw_trace)
        self.flow.store.write_json(
            "builder-trace.json",
            {
                "session": session,
                "path": f"raw-traces/{session}.jsonl",
                "sha256": sha256_file(raw_trace),
                "size": raw_trace.stat().st_size,
            },
        )
        # Per-round behavioral statistics into the flow journal, so cost,
        # tool activity, and error counts can be studied round over round.
        from .supervision import TraceStats

        stats = TraceStats.from_lines(
            raw_trace.read_text(encoding="utf-8", errors="replace").splitlines()
        )
        self.flow.store.journal(
            "builder_round",
            round=self.flow.state.current_round,
            session=session,
            turns=stats.turns,
            tool_uses=stats.tool_uses,
            errors=stats.errors,
            cost_usd=round(stats.total_cost_usd, 4),
            output_tokens=stats.output_tokens,
        )

    def _publish_review_bundle(self) -> None:
        diff_file = self.flow.store.root / "candidate.patch"
        log_file = self.flow.store.root / "candidate-log.txt"
        summary = self.flow.store.root / "benchmark-summary.json"
        if not all(path.is_file() for path in (diff_file, log_file, summary)):
            raise RuntimeError("candidate checkpoint is incomplete")
        reset = self.sandbox.run(
            (
                "sudo",
                "-n",
                "sh",
                "-c",
                "rm -rf /opt/lda/review && "
                "install -d -o user -g user -m 0755 /opt/lda/review",
            )
        )
        if not reset.ok:
            raise RuntimeError("could not prepare review bundle directory")
        for local in (diff_file, log_file, summary):
            self.sandbox.put(local, f"/opt/lda/review/{local.name}")
        sealed = self.sandbox.run(
            (
                "sudo",
                "-n",
                "sh",
                "-c",
                "chown -R root:root /opt/lda/review && "
                "find /opt/lda/review -type f -exec chmod 0444 {} + && "
                "chmod 0555 /opt/lda/review",
            )
        )
        if not sealed.ok:
            raise RuntimeError("could not seal review bundle")

    def certify_candidate(
        self,
        sandbox_factory: Callable[[], Sandbox],
        *,
        bootstrap_root: Path | None = None,
        replications: int = 2,
    ) -> dict:
        """A/B/A' realized: replay setup and candidate in fresh sandboxes.

        Certification defeats two failure modes at once. Placement noise:
        each fresh sandbox lands on its own host, so a speedup that only
        existed on one machine does not certify. Builder-side tampering:
        nothing from the Builder's environment survives into certification
        except the durable git patch.
        """
        if replications < 1:
            raise ValueError("replications must be positive")
        patch = self.flow.store.root / "candidate.patch"
        if not patch.is_file() or not patch.stat().st_size:
            raise RuntimeError("no durable candidate patch to certify")
        entries = []
        for replication in range(replications):
            sandbox = sandbox_factory()
            try:
                entries.append(
                    self._certify_once(sandbox, replication, bootstrap_root, patch)
                )
            finally:
                close = getattr(sandbox, "close", None)
                if close is not None:
                    try:
                        close()
                    except Exception:
                        pass
        summary = {
            "passed": True,
            "replications": len(entries),
            "results": entries,
        }
        self.flow.store.write_json("certification-summary.json", summary)
        self.flow.state.metadata["certified"] = True
        self.flow.store.save_state(self.flow.state)
        return summary

    def _certify_once(
        self,
        sandbox: Sandbox,
        replication: int,
        bootstrap_root: Path | None,
        patch: Path,
    ) -> dict:
        tag = f"certification sandbox {replication}"
        bootstrap = getattr(sandbox, "bootstrap_assets", None)
        if bootstrap is not None and bootstrap_root is not None:
            # Certification replays the run's pinned assets, never the
            # repository's current state.
            snapshot = self.flow.store.root / "assets-snapshot"
            bootstrap(snapshot if snapshot.is_dir() else bootstrap_root)
        check = sandbox.run(self.card.baseline.verification_command(), timeout_seconds=300)
        if not check.ok:
            raise RuntimeError(f"{tag}: baseline verification failed: {check.stderr[-800:]}")
        for command in self.card.setup_commands:
            result = sandbox.run(
                ("env", *self._baseline_env(), *command),
                timeout_seconds=_setup_timeout(),
            )
            if not result.ok:
                raise RuntimeError(f"{tag}: setup failed: {command}: {result.stderr[-800:]}")
        remote_patch = f"/scratch/lda-hm/{self.flow.run_id}-cert-candidate.patch"
        sandbox.put(patch, remote_patch)
        for arguments in (("apply", "--check", remote_patch), ("apply", "--index", remote_patch)):
            result = sandbox.run(("git", "-C", "/opt/lda/work", *arguments))
            if not result.ok:
                raise RuntimeError(f"{tag}: candidate patch does not apply cleanly")
        committed = sandbox.run(
            (
                "git",
                "-C",
                "/opt/lda/work",
                "commit",
                "-m",
                f"LDA certification candidate {self.flow.run_id}",
            )
        )
        if not committed.ok:
            raise RuntimeError(f"{tag}: could not commit candidate")
        suite = FenceSuite(sandbox, self.card, trace_required=False)
        fence_results = suite.run()
        failures = [result.reason for result in fence_results if not result.passed]
        if failures:
            raise RuntimeError(f"{tag}: fences failed: " + "; ".join(failures[:3]))
        runner = BenchmarkRunner(sandbox)
        comparisons = []
        cert_dir = self.flow.store.root / "benchmarks" / "certification" / f"rep{replication}"
        for spec in (*self.card.micro_benchmarks, *self.card.end_to_end_benchmarks):
            # Calibrate the instrument on this host before trusting it: the
            # baseline against itself must not resolve an effect, or a
            # certified speedup here cannot be told from measurement bias.
            if spec.min_speedup_percent is not None:
                null_a, null_b = runner.run_null(spec)
                if null_a.successful and null_b.successful:
                    null_comparison = compare_paired(spec, null_a, null_b)
                    null_a.write(cert_dir / f"{spec.layer}-{spec.name}-nullA.json")
                    null_b.write(cert_dir / f"{spec.layer}-{spec.name}-nullB.json")
                    judge_null_run(
                        spec,
                        null_comparison,
                        spec.min_speedup_percent,
                        stage=f"certify-{replication}-null",
                    )
            baseline, candidate, comparison = paired_with_retry(
                runner, spec, stage=f"certify-{replication}"
            )
            baseline.write(cert_dir / f"{spec.layer}-{spec.name}-baseline.json")
            candidate.write(cert_dir / f"{spec.layer}-{spec.name}-candidate.json")
            entry = comparison.to_dict() | {
                "max_regression_percent": spec.max_regression_percent,
                "min_speedup_percent": spec.min_speedup_percent,
            }
            if spec.holdout_min_speedup_percent is not None:
                # Fresh secret seed per replication: no builder anywhere has
                # ever seen these fixtures.
                seed = random.SystemRandom().randrange(1, 2**31)
                directory = f"/scratch/lda-hm/{self.flow.run_id}-cert-holdout-{replication}"
                prepared = sandbox.run(
                    holdout_setup_command(spec, directory, seed), timeout_seconds=600
                )
                if not prepared.ok:
                    raise RuntimeError(
                        f"{tag}: holdout fixture generation failed: {prepared.stderr[-500:]}"
                    )
                _, _, holdout = paired_with_retry(
                    runner,
                    spec,
                    stage=f"certify-holdout-{replication}",
                    envs={spec.holdout_env: directory},
                    min_speedup_override=spec.holdout_min_speedup_percent,
                )
                entry["holdout"] = holdout.to_dict() | {
                    "min_speedup_percent": spec.holdout_min_speedup_percent,
                }
            comparisons.append(entry)
        cpu = sandbox.run(("sh", "-c", "lscpu | sed -n 's/^Model name:[[:space:]]*//p'"))
        return {
            "sandbox_id": sandbox.sandbox_id,
            "cpu": " ".join(cpu.stdout.split()) if cpu.ok else "unknown",
            "comparisons": comparisons,
        }

    @staticmethod
    def default_gate_context(flow: HumanizeFlow) -> GateContext:
        return GateContext(
            workspace=flow.workspace,
            store=flow.store,
            state=flow.state,
            config=flow.config,
            current_branch=flow.state.start_branch,
            worktree_clean=True,
        )

    @staticmethod
    def sandbox_gate_context(
        flow: HumanizeFlow,
        sandbox: Sandbox,
        *,
        target_workspace: str = "/opt/lda/work",
    ) -> GateContext:
        """Derive Git facts inside E2B instead of trusting the host process."""
        branch = sandbox.run(("git", "-C", target_workspace, "branch", "--show-current"))
        status = sandbox.run(("git", "-C", target_workspace, "status", "--porcelain"))
        diff = sandbox.run(
            (
                "git",
                "-C",
                target_workspace,
                "diff",
                "--numstat",
                f"{flow.state.base_commit}..HEAD",
            )
        )
        ahead = sandbox.run(("git", "-C", target_workspace, "rev-list", "--count", "@{u}..HEAD"))
        changed: list[str] = []
        if diff.ok:
            for line in diff.stdout.splitlines():
                fields = line.split("\t", 2)
                if len(fields) == 3:
                    try:
                        additions = int(fields[0]) if fields[0] != "-" else 0
                        deletions = int(fields[1]) if fields[1] != "-" else 0
                    except ValueError:
                        changed.append(fields[2])
                        continue
                    if additions + deletions > flow.config.large_file_line_limit:
                        changed.append(fields[2])
        unpushed = False
        if ahead.ok:
            try:
                unpushed = int(ahead.stdout.strip() or "0") > 0
            except ValueError:
                unpushed = True
        return GateContext(
            workspace=flow.workspace,
            store=flow.store,
            state=flow.state,
            config=flow.config,
            current_branch=branch.stdout.strip() if branch.ok else "",
            worktree_clean=status.ok and not status.stdout.strip(),
            has_unpushed_commits=unpushed,
            large_changed_files=tuple(changed),
        )
