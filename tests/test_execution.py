from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from lda_hm import (
    BenchmarkRunner,
    BenchmarkSpec,
    CompatibilityBoundary,
    FakeSandbox,
    FenceBlocked,
    FenceSuite,
    HumanizeFlow,
    HumanizeStages,
    PackagePriority,
    TaskCard,
    SandboxResult,
    select_package_batch,
)


class ExecutionContractTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.trace = self.root / "builder.jsonl"
        self.trace.write_text(
            json.dumps({"kind": "prompt", "role": "builder"})
            + "\n"
            + json.dumps({"kind": "stop", "role": "builder"})
            + "\n",
            encoding="utf-8",
        )
        self.card = TaskCard(
            package=PackagePriority("libpng", 0.9, 0.95, 0.85, rationale="system-wide image path"),
            goal="Optimize libpng without changing the Ubuntu replacement contract",
            source_reference="ubuntu:26.04/libpng@baseline",
            setup_commands=(("git", "init"),),
            baseline_tests=(("make", "check"),),
            dependency_tests=(("./run-dependency-tests",),),
            abi_checks=(("abidiff", "baseline.xml", "candidate.xml"),),
            ffi_checks=(("./ffi-smoke",),),
            behavior_checks=(("./behavior-smoke",),),
            package_lifecycle_checks=(("./package-lifecycle",),),
            security_checks=(("./security-defaults",),),
            result_equivalence_checks=(("./result-equivalence",),),
            micro_benchmarks=(BenchmarkSpec("png-decode", "micro", ("./micro",), repetitions=2),),
            end_to_end_benchmarks=(BenchmarkSpec("browser-render", "end_to_end", ("./e2e",)),),
            compatibility=CompatibilityBoundary(),
        )

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_priority_and_both_benchmark_layers(self) -> None:
        selected = select_package_batch(
            [self.card.package, PackagePriority("zlib", 0.8, 0.8, 0.8)], limit=1
        )
        self.assertEqual(selected[0].package, "libpng")
        report = BenchmarkRunner(FakeSandbox()).run(self.card.micro_benchmarks[0])
        self.assertTrue(report.successful)
        self.assertEqual(len(report.observations), 2)

    def test_fence_requires_all_commands_and_trace(self) -> None:
        results = FenceSuite(FakeSandbox(), self.card, trace_file=self.trace).run()
        self.assertTrue(all(result.passed for result in results))

    def test_fence_rejects_cheating_trace(self) -> None:
        self.trace.write_text('{"kind":"tool_call","cheat":true}\n', encoding="utf-8")
        results = FenceSuite(FakeSandbox(), self.card, trace_file=self.trace).run()
        self.assertFalse(results[-1].passed)

    def test_failed_fence_blocks_reviewer(self) -> None:
        from lda_hm.runtime import SessionTopology

        class Session:
            def __init__(self, response):
                self.response = response

            def ask(self, prompt, *, schema=None):
                return self.response

        class Agent:
            def __init__(self, response):
                self.response = response
                self.opened = 0

            def new_session(self, cwd):
                self.opened += 1
                return Session(self.response)

        failing = SandboxResult(("make", "check"), 1, "", "failed", 0.1, "fake-sandbox")
        sandbox = FakeSandbox({("make", "check"): failing})
        reviewer = Agent("ADVANCED")
        topology = SessionTopology(
            drafter=Agent("idea"),
            planner=Agent("plan"),
            analyst=Agent("analysis"),
            builder=Agent("builder summary"),
            reviewer=reviewer,
            cwd=self.root,
        )
        flow = HumanizeFlow(self.root)
        flow.begin("task")
        flow.record_idea("idea")
        flow.record_plan(
            "goal\ncriterion\npositive\nnegative\nboundary\ntask",
            goal_tracker="goal tracker",
        )
        stages = HumanizeStages(
            flow,
            topology,
            fence_suite=FenceSuite(sandbox, self.card, trace_file=self.trace),
        )
        result = stages.review_round(contract="one bounded task")
        self.assertEqual(reviewer.opened, 0)
        self.assertEqual(result.verdict.value, "REGRESSED")
        self.assertEqual(flow.state.phase.value, "implementation")
        self.assertTrue(
            (flow.store.round_dir(0) / "blocked.json").is_file()
        )


if __name__ == "__main__":
    unittest.main()
