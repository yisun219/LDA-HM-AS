from __future__ import annotations

import json
import unittest

from lda_hm import (
    BenchmarkObservation,
    BenchmarkReport,
    BenchmarkSpec,
    compare_paired,
    holdout_setup_command,
    judge_comparison,
    parse_bench_samples,
    scan_candidate_patch_text,
)


def _sample_line(input_name: str, seconds: float, mode: str, output_hash: str = "h") -> str:
    return "LDA_BENCH " + json.dumps(
        {
            "layer": "micro",
            "input": input_name,
            "mode": mode,
            "seconds": seconds,
            "iterations": 100,
            "hash": output_hash,
            "load1": 0.5,
            "steal_ticks": 0,
        }
    )


def _report(name_suffix: str, per_rep_seconds: list[dict], mode: str) -> BenchmarkReport:
    observations = []
    for repetition, inputs in enumerate(per_rep_seconds):
        stdout = "\n".join(
            _sample_line(input_name, seconds, mode) for input_name, seconds in inputs.items()
        )
        observations.append(
            BenchmarkObservation(
                layer="micro",
                name="demo" + name_suffix,
                repetition=repetition,
                exit_code=0,
                duration_seconds=sum(inputs.values()) + 0.4,
                sandbox_id="fake",
                samples=parse_bench_samples(stdout),
            )
        )
    return BenchmarkReport("micro", "demo" + name_suffix, tuple(observations))


SPEC = BenchmarkSpec(
    "demo",
    "micro",
    ("./micro",),
    repetitions=3,
    max_regression_percent=2.0,
    min_speedup_percent=2.0,
)


class BenchmarkAnalysisTest(unittest.TestCase):
    def test_parse_samples_reads_only_marked_lines(self) -> None:
        stdout = "noise\n" + _sample_line("small", 1.25, "baseline") + "\ntrailer"
        samples = parse_bench_samples(stdout)
        self.assertEqual(len(samples), 1)
        self.assertEqual(samples[0].input, "small")
        self.assertAlmostEqual(samples[0].seconds, 1.25)

    def test_nonce_declaration_rejects_forged_lines(self) -> None:
        genuine = '{"input":"small","seconds":2.0,"iterations":1,"cpus":2}'
        forged_bare = '{"input":"small","seconds":0.01,"iterations":1}'
        forged_tag = '{"input":"small","seconds":0.01,"iterations":1}'
        stdout = "\n".join(
            [
                "LDA_BENCH_NONCE abc123",
                # A consumer process can print anything, but it cannot know
                # the nonce, so its lines are ignored.
                "LDA_BENCH " + forged_bare,
                "LDA_BENCH[evil] " + forged_tag,
                "LDA_BENCH_NONCE hijack",
                "LDA_BENCH[abc123] " + genuine,
            ]
        )
        samples = parse_bench_samples(stdout)
        self.assertEqual(len(samples), 1)
        self.assertAlmostEqual(samples[0].seconds, 2.0)
        self.assertEqual(samples[0].cpus, 2)

    def test_invalid_seconds_are_skipped(self) -> None:
        stdout = "\n".join(
            [
                'LDA_BENCH {"input":"a","seconds":0}',
                'LDA_BENCH {"input":"b","seconds":-1}',
                'LDA_BENCH not-json',
                'LDA_BENCH {"input":"c","seconds":1.5}',
            ]
        )
        samples = parse_bench_samples(stdout)
        self.assertEqual([sample.input for sample in samples], ["c"])

    def test_steal_fraction_normalizes_by_cpu_count(self) -> None:
        line = (
            "LDA_BENCH "
            + json.dumps(
                {
                    "input": "small",
                    "seconds": 10.0,
                    "iterations": 1,
                    "steal_ticks": 400,
                    "cpus": 8,
                    "hash": "h",
                }
            )
        )
        report = BenchmarkReport(
            "micro",
            "demo",
            (
                BenchmarkObservation(
                    layer="micro",
                    name="demo",
                    repetition=0,
                    exit_code=0,
                    duration_seconds=10.0,
                    sandbox_id="fake",
                    samples=parse_bench_samples(line),
                ),
            ),
        )
        spec = BenchmarkSpec("demo", "micro", ("./micro",), repetitions=1)
        comparison = compare_paired(spec, report, report)
        # 400 ticks = 4 steal-seconds machine-wide over 10s on 8 vCPUs -> 5%.
        self.assertAlmostEqual(comparison.max_steal_fraction, 0.05)

    def test_verdict_uses_sandbox_samples_not_host_wall_time(self) -> None:
        baseline = _report("-baseline", [{"small": 1.00}, {"small": 1.01}, {"small": 0.99}], "baseline")
        candidate = _report("-candidate", [{"small": 0.94}, {"small": 0.95}, {"small": 0.93}], "candidate")
        comparison = compare_paired(SPEC, baseline, candidate)
        self.assertGreater(comparison.overall_speedup_percent, 5.0)
        judge_comparison(SPEC, comparison, SPEC.min_speedup_percent, stage="train")

    def test_regression_on_any_input_is_a_veto(self) -> None:
        baseline = _report(
            "-baseline",
            [{"small": 1.0, "large": 2.0}, {"small": 1.0, "large": 2.0}, {"small": 1.0, "large": 2.0}],
            "baseline",
        )
        candidate = _report(
            "-candidate",
            [{"small": 0.8, "large": 2.2}, {"small": 0.8, "large": 2.2}, {"small": 0.8, "large": 2.2}],
            "candidate",
        )
        comparison = compare_paired(SPEC, baseline, candidate)
        with self.assertRaisesRegex(RuntimeError, "regression.*large"):
            judge_comparison(SPEC, comparison, SPEC.min_speedup_percent, stage="train")

    def test_speedup_within_noise_is_not_certified(self) -> None:
        baseline = _report("-baseline", [{"small": 1.00}, {"small": 1.30}, {"small": 0.80}], "baseline")
        candidate = _report("-candidate", [{"small": 0.97}, {"small": 1.24}, {"small": 0.79}], "candidate")
        comparison = compare_paired(SPEC, baseline, candidate)
        with self.assertRaisesRegex(RuntimeError, "within measurement noise"):
            judge_comparison(SPEC, comparison, SPEC.min_speedup_percent, stage="train")

    def test_pathological_spread_is_an_environment_error(self) -> None:
        from lda_hm import BenchmarkEnvironmentError

        # Six clean ~6% wins plus one repetition poisoned by a co-tenant
        # burst: the half-range explodes but the effect direction is clear.
        baseline = _report(
            "-baseline",
            [{"small": 1.00}] * 6 + [{"small": 1.00}],
            "baseline",
        )
        candidate = _report(
            "-candidate",
            [{"small": 0.94}] * 6 + [{"small": 1.18}],
            "candidate",
        )
        comparison = compare_paired(SPEC, baseline, candidate)
        with self.assertRaisesRegex(BenchmarkEnvironmentError, "spread implausible"):
            judge_comparison(SPEC, comparison, SPEC.min_speedup_percent, stage="holdout")

    def test_output_hash_mismatch_fails_closed(self) -> None:
        baseline = _report("-baseline", [{"small": 1.0}], "baseline")
        stdout = _sample_line("small", 0.9, "candidate", output_hash="different")
        candidate = BenchmarkReport(
            "micro",
            "demo-candidate",
            (
                BenchmarkObservation(
                    layer="micro",
                    name="demo-candidate",
                    repetition=0,
                    exit_code=0,
                    duration_seconds=1.0,
                    sandbox_id="fake",
                    samples=parse_bench_samples(stdout),
                ),
            ),
        )
        spec = BenchmarkSpec("demo", "micro", ("./micro",), repetitions=1)
        with self.assertRaisesRegex(ValueError, "output mismatch"):
            compare_paired(spec, baseline, candidate)

    def test_uninstrumented_report_is_rejected(self) -> None:
        empty = BenchmarkReport(
            "micro",
            "demo-baseline",
            (
                BenchmarkObservation(
                    layer="micro",
                    name="demo-baseline",
                    repetition=0,
                    exit_code=0,
                    duration_seconds=1.0,
                    sandbox_id="fake",
                ),
            ),
        )
        spec = BenchmarkSpec("demo", "micro", ("./micro",), repetitions=1)
        with self.assertRaisesRegex(ValueError, "not instrumented"):
            compare_paired(spec, empty, empty)


class TamperScanTest(unittest.TestCase):
    def test_patch_touching_tests_is_blocked(self) -> None:
        patch = "diff --git a/tests/pngtest.sh b/tests/pngtest.sh\n+exit 0\n"
        self.assertTrue(scan_candidate_patch_text(patch))
        patch = "diff --git a/pngvalid.c b/pngvalid.c\n+// weakened\n"
        self.assertTrue(scan_candidate_patch_text(patch))

    def test_nocheck_addition_is_blocked(self) -> None:
        patch = (
            "diff --git a/debian/rules b/debian/rules\n"
            "+export DEB_BUILD_OPTIONS := nocheck\n"
        )
        violations = scan_candidate_patch_text(patch)
        self.assertTrue(any("test-weakening" in v for v in violations))

    def test_legitimate_optimization_patch_passes(self) -> None:
        patch = (
            "diff --git a/debian/rules b/debian/rules\n"
            "+export DEB_CFLAGS_MAINT_APPEND = -O3\n"
            "diff --git a/pngrutil.c b/pngrutil.c\n"
            "+/* vectorized row filter */\n"
        )
        self.assertEqual(scan_candidate_patch_text(patch), [])


class HoldoutSetupTest(unittest.TestCase):
    def test_placeholders_are_substituted(self) -> None:
        spec = BenchmarkSpec(
            "demo",
            "micro",
            ("./micro",),
            holdout_min_speedup_percent=1.0,
            holdout_env="LDA_MICRO_FIXTURE_DIR",
            holdout_setup=("env", "LDA_FIXTURE_DIR={dir}", "LDA_FIXTURE_SEED={seed}", "gen.sh"),
        )
        command = holdout_setup_command(spec, "/tmp/h", 42)
        self.assertEqual(
            command,
            ("env", "LDA_FIXTURE_DIR=/tmp/h", "LDA_FIXTURE_SEED=42", "gen.sh"),
        )

    def test_holdout_policy_requires_setup(self) -> None:
        with self.assertRaises(ValueError):
            BenchmarkSpec(
                "demo",
                "micro",
                ("./micro",),
                holdout_min_speedup_percent=1.0,
            )


if __name__ == "__main__":
    unittest.main()
