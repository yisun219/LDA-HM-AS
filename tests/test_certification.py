from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from lda_hm import (
    BenchmarkSpec,
    CompatibilityBoundary,
    FakeSandbox,
    FenceSuite,
    HumanizeFlow,
    LDAExecution,
    PackagePriority,
    SandboxResult,
    TaskCard,
)
from lda_hm.fence import integrity_manifest_command
from lda_hm.runtime import SessionTopology


def _bench_line(input_name: str, seconds: float) -> str:
    return "LDA_BENCH " + json.dumps(
        {
            "layer": "micro",
            "input": input_name,
            "mode": "any",
            "seconds": seconds,
            "iterations": 10,
            "hash": "h",
            "load1": 0.1,
            "steal_ticks": 0,
        }
    )


class _Agent:
    def __init__(self, response: str = "ok"):
        self.response = response

    def new_session(self, cwd):
        agent = self

        class Session:
            session_id = "builder-1"

            def ask(self, prompt, *, schema=None):
                return agent.response

        return Session()


def _card() -> TaskCard:
    return TaskCard(
        package=PackagePriority("libpng", 0.9, 0.9, 0.9),
        goal="optimize",
        source_reference="ubuntu:26.04/libpng@baseline",
        setup_commands=(("./setup",),),
        baseline_tests=(("./baseline-tests",),),
        dependency_tests=(("./dependency-tests",),),
        abi_checks=(("./abi",),),
        ffi_checks=(("./ffi",),),
        behavior_checks=(("./behavior",),),
        package_lifecycle_checks=(("./lifecycle",),),
        security_checks=(("./security",),),
        result_equivalence_checks=(("./equivalence",),),
        micro_benchmarks=(
            BenchmarkSpec("micro", "micro", ("./micro",), repetitions=3),
        ),
        end_to_end_benchmarks=(
            BenchmarkSpec("e2e", "end_to_end", ("./e2e",), repetitions=3),
        ),
        compatibility=CompatibilityBoundary(),
    )


class _BenchSandbox(FakeSandbox):
    """Fake sandbox whose benchmark commands emit in-sandbox samples."""

    def run(self, command, *, timeout_seconds=900, envs=None):
        joined = " ".join(command)
        if joined.endswith("./micro"):
            return SandboxResult(
                tuple(command), 0, _bench_line("small", 1.0), "", 0.001, self.sandbox_id
            )
        if joined.endswith("./e2e"):
            return SandboxResult(
                tuple(command), 0, _bench_line("render", 2.0), "", 0.001, self.sandbox_id
            )
        return super().run(command, timeout_seconds=timeout_seconds, envs=envs)


class CertificationTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.flow = HumanizeFlow(self.root)
        self.card = _card()
        agent = _Agent()
        self.topology = SessionTopology(
            drafter=agent,
            planner=agent,
            analyst=agent,
            builder=agent,
            reviewer=agent,
            cwd=self.root,
        )
        self.execution = LDAExecution(
            self.flow,
            self.card,
            _BenchSandbox(),
            self.topology,
            require_e2b=False,
        )

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_refuses_without_candidate_patch(self) -> None:
        with self.assertRaisesRegex(RuntimeError, "no durable candidate patch"):
            self.execution.certify_candidate(lambda: _BenchSandbox(), replications=1)

    def test_certifies_in_fresh_sandboxes(self) -> None:
        self.flow.store.write_text("candidate.patch", "diff --git a/x b/x\n+1\n")
        closed = []

        def factory():
            sandbox = _BenchSandbox()
            original_close = sandbox.close

            def close():
                closed.append(sandbox.sandbox_id)
                original_close()

            sandbox.close = close
            return sandbox

        summary = self.execution.certify_candidate(factory, replications=2)
        self.assertTrue(summary["passed"])
        self.assertEqual(summary["replications"], 2)
        self.assertEqual(len(closed), 2)
        stored = json.loads(
            (self.flow.store.root / "certification-summary.json").read_text()
        )
        self.assertTrue(stored["passed"])
        self.assertTrue(self.flow.state.metadata.get("certified"))
        report = (
            self.flow.store.root
            / "benchmarks"
            / "certification"
            / "rep0"
            / "micro-micro-baseline.json"
        )
        self.assertTrue(report.is_file())

    def test_failing_fence_fails_certification(self) -> None:
        self.flow.store.write_text("candidate.patch", "diff --git a/x b/x\n+1\n")

        class FailingFence(_BenchSandbox):
            def run(self, command, *, timeout_seconds=900, envs=None):
                if " ".join(command).endswith("./abi"):
                    return SandboxResult(
                        tuple(command), 1, "", "abi mismatch", 0.001, self.sandbox_id
                    )
                return super().run(command, timeout_seconds=timeout_seconds, envs=envs)

        with self.assertRaisesRegex(RuntimeError, "fences failed"):
            self.execution.certify_candidate(lambda: FailingFence(), replications=1)


class IntegrityFenceTest(unittest.TestCase):
    def test_integrity_mismatch_blocks_everything_else(self) -> None:
        card = _card()
        manifest_command = integrity_manifest_command(card.integrity_paths)
        sandbox = FakeSandbox(
            {
                manifest_command: SandboxResult(
                    manifest_command, 0, "aaaa  /opt/lda/harness/x\n", "", 0.001, "fake-sandbox"
                )
            }
        )
        suite = FenceSuite(
            sandbox,
            card,
            integrity_manifest="bbbb  /opt/lda/harness/x\n",
            trace_required=False,
        )
        results = suite.run()
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].name, "integrity")
        self.assertFalse(results[0].passed)

    def test_integrity_match_passes_through(self) -> None:
        card = _card()
        manifest_command = integrity_manifest_command(card.integrity_paths)
        sandbox = FakeSandbox(
            {
                manifest_command: SandboxResult(
                    manifest_command, 0, "aaaa  /opt/lda/harness/x\n", "", 0.001, "fake-sandbox"
                )
            }
        )
        suite = FenceSuite(
            sandbox,
            card,
            integrity_manifest="aaaa  /opt/lda/harness/x\n",
            trace_required=False,
        )
        results = suite.run()
        self.assertTrue(all(result.passed for result in results))
        self.assertEqual(results[0].name, "integrity")


if __name__ == "__main__":
    unittest.main()
