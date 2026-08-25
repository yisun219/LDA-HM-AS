"""Mission command lifecycle and fail-closed execution."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from .benchmarks import summarize
from .fence import (
    FenceResult,
    cpu_fence,
    run_command_fence,
    source_allowlist,
    trace_fence,
)
from .models import Benchmark, Command, Mission


class Executor(Protocol):
    def run(self, command: Command): ...


@dataclass(frozen=True)
class MissionReport:
    mission_id: str
    sandbox_id: str
    fences: tuple[FenceResult, ...]
    accepted: bool
    reward: float
    snapshot_id: str | None = None
    candidate_debs: tuple[str, ...] = ()


def command_argv(commands: tuple[Command, ...]) -> tuple[tuple[str, ...], ...]:
    return tuple(command.argv for command in commands)


def run_group(name: str, commands: tuple[Command, ...], executor: Executor) -> FenceResult:
    return run_command_fence(name, command_argv(commands), executor.run)


def _result_value(output: str) -> float | None:
    for line in reversed(output.splitlines()):
        if line.startswith("RESULT="):
            try:
                return float(line.split("=", 1)[1].strip())
            except ValueError:
                return None
    return None


def run_benchmark(benchmark: Benchmark, executor: Executor) -> FenceResult:
    for _ in range(benchmark.warmups):
        executor.run(benchmark.baseline)
        executor.run(benchmark.candidate)
    baseline_values: list[float] = []
    candidate_values: list[float] = []
    for _ in range(benchmark.samples):
        baseline = executor.run(benchmark.baseline)
        candidate = executor.run(benchmark.candidate)
        if baseline.returncode or candidate.returncode:
            return FenceResult(benchmark.name, False, "benchmark command failed", 0.0)
        baseline_value = _result_value(f"{baseline.stdout}\n{baseline.stderr}")
        candidate_value = _result_value(f"{candidate.stdout}\n{candidate.stderr}")
        if baseline_value is None or candidate_value is None:
            return FenceResult(benchmark.name, False, "benchmark did not emit RESULT=", 0.0)
        baseline_values.append(baseline_value)
        candidate_values.append(candidate_value)
    report = summarize(
        benchmark.name,
        tuple(baseline_values),
        tuple(candidate_values),
        lower_is_better=benchmark.lower_is_better,
        max_relative_mad=benchmark.max_relative_mad,
        min_speedup=benchmark.min_speedup,
    )
    return FenceResult(
        benchmark.name,
        report.passed,
        json.dumps({"result": report.__dict__}),
        report.reward if report.passed else 0.0,
    )


def package_fence(mission: Mission, executor: Executor) -> FenceResult:
    expected = mission.package
    fields = " ".join(expected.control_fields)
    script = (
        "set -eu; base=$(printf '%s\\n' .lda/baseline-debs/*.deb | head -n1); "
        "cand=$(printf '%s\\n' .lda/candidate-debs/*.deb | head -n1); "
        f"test \"$(dpkg-deb -f \"$cand\" Package)\" = {expected.binary_package}; "
        f"test \"$(dpkg-deb -f \"$cand\" Architecture)\" = {expected.architecture}; "
        f"test \"$(dpkg-deb -f \"$cand\" 'Multi-Arch')\" = {expected.multi_arch}; "
        "dpkg --compare-versions \"$(dpkg-deb -f \"$base\" Version)\" lt "
        "\"$(dpkg-deb -f \"$cand\" Version)\"; "
        f"for field in {fields}; do test \"$(dpkg-deb -f \"$base\" \"$field\")\" = "
        f"\"$(dpkg-deb -f \"$cand\" \"$field\")\"; done"
    )
    return run_group(
        "package_programmatic",
        (Command(argv=("bash", "-lc", script)),),
        executor,
    )


def abi_fence(mission: Mission, executor: Executor) -> FenceResult:
    checks = []
    for path in mission.package.shared_objects:
        relative = path.lstrip("/")
        checks.append(
            f"test -f .lda/baseline-root/{relative} && "
            f"test -f .lda/candidate-root/{relative} && "
            f"readelf -d .lda/baseline-root/{relative} >/dev/null && "
            f"readelf -d .lda/candidate-root/{relative} >/dev/null && "
            f"objdump -T .lda/baseline-root/{relative} >/dev/null && "
            f"objdump -T .lda/candidate-root/{relative} >/dev/null && "
            f"abidiff .lda/baseline-root/{relative} .lda/candidate-root/{relative}"
        )
    return run_group(
        "abi_programmatic",
        (Command(argv=("bash", "-lc", "set -eu; " + "; ".join(checks))),),
        executor,
    )


def header_fence(mission: Mission, executor: Executor) -> FenceResult:
    includes = " ".join(
        f"-include {path.removeprefix('/usr/include/')}"
        for path in mission.package.headers
    )
    command = (
        "printf 'int main(void){return 0;}\\n' | cc -fsyntax-only "
        f"-I .lda/candidate-root/usr/include {includes} -x c -"
    )
    return run_group(
        "header_programmatic",
        (Command(argv=("bash", "-lc", command)),),
        executor,
    )


def remote_source_allowlist(mission: Mission, executor: Executor) -> FenceResult:
    allowed = json.dumps(list(mission.allowed_source_paths))
    globs = json.dumps(list(mission.allowed_untracked_globs))
    script = f'''import fnmatch, json, subprocess
allowed = {allowed}
globs = {globs}
lines = subprocess.check_output(
    ["git", "status", "--porcelain", "--untracked-files=all"], text=True
).splitlines()
bad = []
for line in lines:
    path = line[3:].strip()
    if not any(path == item or path.startswith(item.rstrip("/") + "/") for item in allowed):
        if not any(fnmatch.fnmatch(path, pattern) for pattern in globs):
            bad.append(path)
if bad:
    raise SystemExit(json.dumps({{"out_of_scope": bad}}))
'''
    return run_group(
        "source_allowlist",
        (Command(argv=("python3", "-c", script)),),
        executor,
    )
def prepare(mission: Mission, executor: Executor) -> tuple[FenceResult, ...]:
    results = [run_group("source_acquire", mission.commands.source_acquire, executor)]
    results.append(run_group("baseline_download", mission.commands.baseline_download, executor))
    results.append(run_group("baseline_extract", mission.commands.baseline_extract, executor))
    return tuple(results)


def build(mission: Mission, executor: Executor) -> tuple[FenceResult, ...]:
    return (
        run_group("clean_candidate", mission.commands.clean_candidate, executor),
        run_group("build_candidate", mission.commands.build_candidate, executor),
        run_group("candidate_extract", mission.commands.candidate_extract, executor),
    )


def verify(
    mission: Mission, executor: Executor, root: Path | None, trace: Path
) -> tuple[FenceResult, ...]:
    results = [
        package_fence(mission, executor),
        run_group("package_declared", mission.commands.package_fence, executor),
        abi_fence(mission, executor),
        run_group("abi_declared", mission.commands.abi_fence, executor),
        header_fence(mission, executor),
        run_group("api_header_declared", mission.commands.header_fence, executor),
        run_group("ffi", mission.commands.ffi_fence, executor),
        run_group("self_test", mission.commands.self_test, executor),
        run_group("dependency_test", mission.commands.dependency_test, executor),
        run_group(
            "humanize_review",
            (Command(argv=("bash", "-lc", "test -s .lda/review-approved.json")),),
            executor,
        ),
        (
            source_allowlist(root, mission.allowed_source_paths, mission.allowed_untracked_globs)
            if root is not None
            else remote_source_allowlist(mission, executor)
        ),
        (
            cpu_fence(root, mission.cpu_policy.forbidden_global_flags)
            if root is not None
            else run_group(
                "cpu_policy",
                (
                    Command(
                        argv=(
                            "bash",
                            "-lc",
                            "! git diff --binary | grep -E -- "
                            "'-march=(native|sapphirerapids)'",
                        )
                    ),
                ),
                executor,
            )
        ),
        trace_fence(trace, mission),
    ]
    if all(item.passed for item in results):
        results.extend(run_benchmark(item, executor) for item in mission.benchmarks)
    return tuple(results)


def write_report(path: Path, report: MissionReport) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "mission_id": report.mission_id,
                "sandbox_id": report.sandbox_id,
                "accepted": report.accepted,
                "reward": report.reward,
                "snapshot_id": report.snapshot_id,
                "candidate_debs": report.candidate_debs,
                "fences": [item.__dict__ for item in report.fences],
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
