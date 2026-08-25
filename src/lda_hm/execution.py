from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from .benchmark import BenchmarkReport, BenchmarkRunner
from .fence import FenceResult, FenceSuite
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
        self.flow.state.metadata["sandbox"] = sandbox_manifest()
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
        for command in self.card.setup_commands:
            result = self.sandbox.run(command, timeout_seconds=3600)
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

    def sync_control_artifacts(self) -> None:
        control = "/opt/lda/control"
        self.sandbox.run(("mkdir", "-p", control))
        files = {
            "task-card.json": self.flow.store.root / "task-card.json",
            "plan.md": self.flow.store.root / "plan.md",
            "goal-tracker.md": self.flow.store.root / "goal-tracker.md",
        }
        for name, local in files.items():
            if not local.is_file():
                raise FileNotFoundError(local)
            remote = f"{control}/{name}"
            self.sandbox.put(local, remote)
            result = self.sandbox.run(("chmod", "0444", remote))
            if not result.ok:
                raise RuntimeError(f"could not protect control artifact {name}")

    def capture_baseline(self) -> tuple[BenchmarkReport, ...]:
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
            baseline.write(self.flow.store.root / "benchmarks" / "paired" / f"{spec.layer}-{spec.name}-baseline.json")
            candidate.write(self.flow.store.root / "benchmarks" / "paired" / f"{spec.layer}-{spec.name}-candidate.json")
            comparisons.append(
                {
                    "layer": spec.layer,
                    "name": spec.name,
                    "baseline_median_seconds": baseline.median_seconds,
                    "candidate_median_seconds": candidate.median_seconds,
                    "speedup_percent": (baseline.median_seconds / candidate.median_seconds - 1.0) * 100.0,
                    "max_regression_percent": spec.max_regression_percent,
                }
            )
            reports.extend((baseline, candidate))
        self.flow.store.write_json(
            "benchmark-summary.json",
            {
                "comparisons": comparisons
            },
        )
        return tuple(reports)

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
        diff = sandbox.run(("git", "-C", target_workspace, "diff", "--numstat"))
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
