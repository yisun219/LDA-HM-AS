from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from .benchmark import BenchmarkReport, BenchmarkRunner
from .fence import FenceResult, FenceSuite, sha256_file
from .flow import HumanizeFlow
from .gates import GateContext, GateRunner
from .runtime import SessionTopology
from .sandbox import Sandbox, SandboxUnavailable, sandbox_manifest
from .stages import HumanizeStages
from .task_card import TaskCard


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
    ) -> HumanizeStages:
        suite = FenceSuite(
            self.sandbox,
            self.card,
            trace_file=trace_file,
            trace_remote=trace_remote,
        )
        runner = GateRunner()
        return HumanizeStages(
            self.flow,
            self.topology,
            fence_suite=suite,
            gate_runner=runner,
            gate_context_factory=self.gate_context_factory,
            pre_review_hook=self.run_candidate_benchmarks,
        )

    def bootstrap_template_assets(self, root: Path) -> None:
        """Install the checked-in LDA harness into this E2B sandbox."""
        bootstrap = getattr(self.sandbox, "bootstrap_assets", None)
        if bootstrap is None:
            raise SandboxUnavailable("sandbox does not support E2B asset bootstrap")
        bootstrap(root)

    def prepare_workspace(self, *, target_workspace: str = "/opt/lda/work") -> None:
        release = self.sandbox.run(("sh", "-c", ". /etc/os-release && printf %s \"$VERSION_ID\""))
        if not release.ok or release.stdout.strip() != "26.04":
            raise SandboxUnavailable("lda-base must run Ubuntu 26.04")
        cpu = self.sandbox.run(("sh", "-c", "lscpu | sed -n 's/^Model:[[:space:]]*//p'"))
        if not cpu.ok or cpu.stdout.strip() != "207":
            raise SandboxUnavailable("sandbox CPU model is not the Xeon 6548Y+ compatible model 207")
        baseline_check = self.sandbox.run(self.card.baseline.verification_command(), timeout_seconds=300)
        if not baseline_check.ok:
            raise SandboxUnavailable(
                "baseline identity verification failed: " + baseline_check.stderr[-1200:]
            )
        self.flow.state.metadata["baseline"] = self.card.baseline.canonical()
        self.flow.state.metadata["baseline_digest"] = self.card.baseline.digest()
        self.flow.state.metadata["baseline_verified"] = True
        self.flow.store.write_json("baseline.json", self.card.baseline.canonical())
        for command in self.card.setup_commands:
            result = self.sandbox.run(("env", *self._baseline_env(), *command), timeout_seconds=3600)
            if not result.ok:
                raise RuntimeError(f"source setup failed: {command}: {result.stderr[-1000:]}")
        branch = self.sandbox.run(("git", "-C", target_workspace, "branch", "--show-current"))
        commit = self.sandbox.run(("git", "-C", target_workspace, "rev-parse", "HEAD"))
        if not branch.ok or not commit.ok:
            raise RuntimeError("prepared target workspace must be a Git repository")
        self.flow.state.start_branch = branch.stdout.strip()
        self.flow.state.base_branch = branch.stdout.strip()
        self.flow.state.base_commit = commit.stdout.strip()
        self.flow.state.metadata["source_reference"] = self.card.source_reference
        self.flow.store.save_state(self.flow.state)

    def restore_candidate(self, *, target_workspace: str = "/opt/lda/work") -> None:
        """Rehydrate the latest durable candidate into a newly created Sandbox."""
        patch = self.flow.store.root / "candidate.patch"
        if patch.is_file() and patch.stat().st_size:
            remote_patch = "/tmp/lda-resume-candidate.patch"
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
        raw_trace = self.flow.store.root / "raw-traces" / "builder-1.jsonl"
        if raw_trace.is_file() and raw_trace.stat().st_size:
            remote_trace = "/opt/lda/agent-state/traces/builder-1.jsonl"
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
                raise RuntimeError(f"baseline benchmark failed: {report.layer}/{report.name}")
            report.write(self.flow.store.root / "benchmarks" / "baseline" / f"{report.layer}-{report.name}.json")
        self.flow.state.metadata["baseline_captured"] = True
        self.flow.store.save_state(self.flow.state)
        return tuple(reports)

    def run_candidate_benchmarks(self) -> tuple[BenchmarkReport, ...]:
        self._checkpoint_candidate()
        prepared = self.sandbox.run(
            ("/opt/lda/harness/checks/ensure-libpng-candidate.sh",),
            timeout_seconds=3600,
        )
        if not prepared.ok:
            raise RuntimeError(
                "candidate package build failed before benchmarking: "
                + prepared.stderr[-1200:]
            )
        runner = BenchmarkRunner(self.sandbox)
        reports: list[BenchmarkReport] = []
        specs = (*self.card.micro_benchmarks, *self.card.end_to_end_benchmarks)
        comparisons = []
        for spec in specs:
            baseline, candidate = runner.run_paired(spec)
            if not baseline.successful or not candidate.successful:
                raise RuntimeError(f"paired benchmark failed: {spec.layer}/{spec.name}")
            allowed = baseline.median_seconds * (1.0 + spec.max_regression_percent / 100.0)
            if candidate.median_seconds > allowed:
                raise RuntimeError(
                    f"benchmark regression: {spec.layer}/{spec.name}: "
                    f"candidate={candidate.median_seconds:.6f}s baseline={baseline.median_seconds:.6f}s"
                )
            speedup = (baseline.median_seconds / candidate.median_seconds - 1.0) * 100.0
            if spec.min_speedup_percent is not None and speedup < spec.min_speedup_percent:
                raise RuntimeError(
                    f"benchmark speedup target not met: {spec.layer}/{spec.name}: "
                    f"speedup={speedup:.3f}% required={spec.min_speedup_percent:.3f}%"
                )
            baseline.write(self.flow.store.root / "benchmarks" / "paired" / f"{spec.layer}-{spec.name}-baseline.json")
            candidate.write(self.flow.store.root / "benchmarks" / "paired" / f"{spec.layer}-{spec.name}-candidate.json")
            comparisons.append(
                {
                    "layer": spec.layer,
                    "name": spec.name,
                    "baseline_median_seconds": baseline.median_seconds,
                    "candidate_median_seconds": candidate.median_seconds,
                    "speedup_percent": speedup,
                    "max_regression_percent": spec.max_regression_percent,
                    "min_speedup_percent": spec.min_speedup_percent,
                }
            )
            reports.extend((baseline, candidate))
        self.flow.store.write_json(
            "benchmark-summary.json",
            {
                "comparisons": comparisons
            },
        )
        self._publish_review_bundle()
        return tuple(reports)

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
        raw_trace = self.flow.store.root / "raw-traces" / "builder-1.jsonl"
        self.sandbox.get(
            "/opt/lda/agent-state/traces/builder-1.jsonl",
            raw_trace,
        )
        self.flow.store.write_json(
            "builder-trace.json",
            {
                "path": "raw-traces/builder-1.jsonl",
                "sha256": sha256_file(raw_trace),
                "size": raw_trace.stat().st_size,
            },
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
