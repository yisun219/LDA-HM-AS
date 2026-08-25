"""Argus-style Campaign Controller around one E2B Sandbox per Mission."""

from __future__ import annotations

import concurrent.futures
import json
import os
import re
from dataclasses import dataclass
from pathlib import Path

from .benchmarks import geomean, summarize
from .fence import FenceResult, run_command_fence
from .gateway import GatewayError, SandboxHandle, create_sandbox, require_e2b
from .lifecycle import MissionReport, build, prepare, verify, write_report
from .models import Campaign, Command, Mission
from .priority import RankedMission, rank_missions
from .security import redact


class SandboxExecutor:
    def __init__(self, handle: SandboxHandle):
        self.handle = handle

    def run(self, command: Command):
        sandbox = self.handle.sandbox
        if not hasattr(sandbox, "commands"):
            raise GatewayError("E2B SDK sandbox command API is unavailable")
        result = sandbox.commands.run(
            " ".join(_quote(item) for item in command.argv),
            timeout=command.timeout_seconds,
            cwd=command.cwd,
            envs=command.env,
        )
        return type(
            "Result",
            (),
            {
                "returncode": int(getattr(result, "exit_code", 1)),
                "stdout": redact(str(getattr(result, "stdout", ""))),
                "stderr": redact(str(getattr(result, "stderr", ""))),
            },
        )()

    def write_text(self, path: str, content: str) -> None:
        self.handle.sandbox.files.write(path, content)

    def read_text(self, path: str) -> str:
        return str(self.handle.sandbox.files.read(path, format="text"))

    def read_bytes(self, path: str) -> bytes:
        data = self.handle.sandbox.files.read(path, format="bytes")
        return bytes(data)

    def write_bytes(self, path: str, content: bytes) -> None:
        self.handle.sandbox.files.write(path, content)


def _quote(value: str) -> str:
    return "'" + value.replace("'", "'\\''") + "'"


@dataclass(frozen=True)
class DryRun:
    ranked: tuple[RankedMission, ...]
    selected: tuple[str, ...]
    skipped: tuple[str, ...]


class CampaignController:
    def __init__(self, campaign: Campaign, output: Path):
        self.campaign = campaign
        self.output = output

    def dry_run(self) -> DryRun:
        ranked = tuple(rank_missions(self.campaign.missions, self.campaign.weights))
        selected = tuple(item.mission.id for item in ranked[: self.campaign.top_k])
        skipped = tuple(item.mission.id for item in ranked[self.campaign.top_k :])
        return DryRun(ranked, selected, skipped)

    def run(self) -> dict:
        require_e2b(self.campaign.e2b)
        if not any(os.getenv(name) for name in self.campaign.agents.forward_env):
            raise GatewayError("missing model credential for configured agent")
        ranked = self.dry_run()
        selected = [item.mission for item in ranked.ranked[: self.campaign.top_k]]
        self.output.mkdir(parents=True, exist_ok=True)
        with concurrent.futures.ThreadPoolExecutor(max_workers=self.campaign.concurrency) as pool:
            reports = list(pool.map(self.run_mission, selected))
        accepted = [report for report in reports if report.accepted]
        summary = {
            "campaign": self.campaign.name,
            "selected": ranked.selected,
            "skipped": ranked.skipped,
            "missions": [report.__dict__ for report in reports],
            "accepted": [report.mission_id for report in accepted],
            "portfolio": self.run_portfolio(accepted) if len(accepted) == len(selected) else {
                "accepted": False,
                "reward": 0.0,
                "reason": "not every selected Mission was accepted",
            },
        }
        summary["portfolio_reward"] = float(summary["portfolio"].get("reward", 0.0))
        (self.output / "campaign-report.json").write_text(
            json.dumps(summary, indent=2) + "\n", encoding="utf-8"
        )
        return summary

    def run_portfolio(self, reports: list[MissionReport]) -> dict:
        """Run campaign benchmarks in clean official and candidate peer sandboxes."""
        official = create_sandbox(self.campaign.e2b, self.campaign.agents.forward_env)
        candidate = create_sandbox(self.campaign.e2b, self.campaign.agents.forward_env)
        official_exec = SandboxExecutor(official)
        candidate_exec = SandboxExecutor(candidate)
        try:
            candidate_exec.run(
                Command(argv=("bash", "-lc", "mkdir -p /workspace/portfolio"))
            )
            for report in reports:
                for local in report.candidate_debs:
                    path = Path(local)
                    candidate_exec.write_bytes(
                        f"/workspace/portfolio/{path.name}", path.read_bytes()
                    )
            install = candidate_exec.run(
                Command(
                    argv=(
                        "bash",
                        "-lc",
                        "dpkg -i /workspace/portfolio/*.deb && apt-get -f install -y",
                    ),
                    timeout_seconds=1800,
                )
            )
            if install.returncode:
                return {"accepted": False, "reward": 0.0, "reason": "candidate install failed"}
            speedups: list[float] = []
            results: list[dict] = []
            for benchmark in self.campaign.campaign_benchmarks:
                baseline_values = self._sample_peer(
                    official_exec, benchmark.baseline, benchmark.samples
                )
                candidate_values = self._sample_peer(
                    candidate_exec, benchmark.candidate, benchmark.samples
                )
                if not baseline_values or not candidate_values:
                    return {
                        "accepted": False,
                        "reward": 0.0,
                        "reason": f"benchmark failed: {benchmark.name}",
                    }
                result = summarize(
                    benchmark.name,
                    tuple(baseline_values),
                    tuple(candidate_values),
                    lower_is_better=benchmark.lower_is_better,
                    max_relative_mad=benchmark.max_relative_mad,
                    min_speedup=benchmark.min_speedup,
                )
                if not result.passed:
                    return {
                        "accepted": False,
                        "reward": 0.0,
                        "reason": f"benchmark rejected: {benchmark.name}",
                    }
                if result.speedup < 1.0 - self.campaign.portfolio_max_regression:
                    return {
                        "accepted": False,
                        "reward": 0.0,
                        "reason": f"portfolio regression: {benchmark.name}",
                    }
                speedups.append(result.speedup)
                results.append(result.__dict__)
            reward = geomean(tuple(speedups))
            accepted = reward >= self.campaign.portfolio_min_geomean_speedup
            return {
                "accepted": accepted,
                "reward": reward if accepted else 0.0,
                "benchmarks": results,
            }
        finally:
            official.sandbox.kill()
            candidate.sandbox.kill()

    @staticmethod
    def _sample_peer(executor: SandboxExecutor, command: Command, samples: int) -> list[float]:
        values: list[float] = []
        for _ in range(samples):
            result = executor.run(command)
            if result.returncode:
                return []
            matches = re.findall(
                r"RESULT=([0-9]+(?:\.[0-9]+)?)",
                f"{result.stdout}\n{result.stderr}",
            )
            if not matches:
                return []
            values.append(float(matches[-1]))
        return values

    def run_mission(self, mission: Mission) -> MissionReport:
        handle = create_sandbox(
            self.campaign.e2b,
            self.campaign.agents.forward_env,
            mission.snapshot_id,
        )
        executor = SandboxExecutor(handle)
        mission_output = self.output / mission.id
        mission_output.mkdir(parents=True, exist_ok=True)
        executor.write_text("/workspace/mission/TASK.md", self._mission_task(mission))
        executor.write_text(
            "/workspace/mission/mission.json", mission.model_dump_json(indent=2) + "\n"
        )
        fences = list(prepare(mission, executor))
        fences.append(self._run_humanize(executor))
        if all(item.passed for item in fences):
            fences.extend(build(mission, executor))
        if all(item.passed for item in fences):
            self._collect_trace(executor)
            trace = mission_output / "humanize.trace.jsonl"
            try:
                trace.write_text(
                    executor.read_text("/workspace/mission/humanize.trace.jsonl"),
                    encoding="utf-8",
                )
            except Exception as exc:
                trace.write_text(json.dumps({"error": redact(str(exc))}) + "\n", encoding="utf-8")
            fences.extend(verify(mission, executor, None, trace))
        candidate_debs = self._download_candidate_debs(executor, mission_output)
        if not candidate_debs:
            fences.append(
                FenceResult(
                    "candidate_artifacts",
                    False,
                    "no candidate .deb was produced",
                    0.0,
                )
            )
        snapshot_id = handle.snapshot() if fences and all(item.passed for item in fences) else None
        accepted = bool(fences) and all(item.passed for item in fences)
        reward = 1.0 if accepted else 0.0
        report = MissionReport(
            mission.id,
            handle.sandbox_id,
            tuple(fences),
            accepted,
            reward,
            snapshot_id,
            tuple(candidate_debs),
        )
        write_report(mission_output / "mission-report.json", report)
        return report

    def _mission_task(self, mission: Mission) -> str:
        return (
            f"Optimize {mission.source_package} on Ubuntu 26.04 in /workspace/mission.\n"
            "You are the Builder in a Humanize Ralph loop. Modify only allowed production "
            "paths. Run the declared build, hard-fence, and benchmark commands. Never modify "
            "tests, benchmarks, policy, validation, or baseline artifacts. A completion claim "
            "is not evidence; leave command output and review artifacts in .lda.\n\n"
            + mission.model_dump_json(indent=2)
        )

    def _run_humanize(self, executor: SandboxExecutor):
        command = Command(
            argv=(
                "bash",
                "-lc",
                "cd /workspace/mission && hmz exec -f /opt/lda/flows/lda "
                f"-a {_quote(self.campaign.agents.builder)} "
                f"-a {_quote(self.campaign.agents.reviewer)} "
                '"$(cat TASK.md)"',
            ),
            timeout_seconds=self.campaign.e2b.timeout_seconds,
        )
        return run_command_fence("humanize_flow", (command.argv,), executor.run)

    @staticmethod
    def _collect_trace(executor: SandboxExecutor) -> None:
        executor.run(
            Command(
                argv=(
                    "bash",
                    "-lc",
                    "hmz trace collect /workspace/mission --all "
                    "--output /workspace/mission/humanize.trace.jsonl",
                ),
                timeout_seconds=600,
            )
        )

    @staticmethod
    def _download_candidate_debs(executor: SandboxExecutor, output: Path) -> list[str]:
        result = executor.run(
            Command(
                argv=(
                    "bash",
                    "-lc",
                    "find /workspace/mission/.lda/candidate-debs -type f -name '*.deb' -print",
                ),
                timeout_seconds=120,
            )
        )
        if result.returncode:
            return []
        downloaded: list[str] = []
        for remote in result.stdout.splitlines():
            remote = remote.strip()
            if not remote:
                continue
            local = output / Path(remote).name
            try:
                local.write_bytes(executor.read_bytes(remote))
            except OSError:
                return []
            downloaded.append(str(local))
        return downloaded
