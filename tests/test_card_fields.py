from __future__ import annotations

import json
import unittest
from pathlib import Path

from lda_hm import BenchmarkSpec, PackagePriority, TaskCard


def _minimal_card(**overrides) -> TaskCard:
    values = dict(
        package=PackagePriority("libcairo2", 0.8, 0.8, 0.8),
        goal="optimize",
        source_reference="ubuntu:resolute/cairo=1@snap",
        setup_commands=(("true",),),
        baseline_tests=(("true",),),
        dependency_tests=(("true",),),
        abi_checks=(("true",),),
        ffi_checks=(("true",),),
        behavior_checks=(("true",),),
        package_lifecycle_checks=(("true",),),
        security_checks=(("true",),),
        result_equivalence_checks=(("true",),),
        micro_benchmarks=(BenchmarkSpec("m", "micro", ("m",)),),
        end_to_end_benchmarks=(BenchmarkSpec("e", "end_to_end", ("e",)),),
    )
    values.update(overrides)
    return TaskCard(**values)


class CardFieldTest(unittest.TestCase):
    def test_candidate_build_and_selfcheck_roundtrip(self) -> None:
        card = _minimal_card(
            candidate_build=("env", "X=1", "/opt/build.sh"),
            selfcheck_commands=(("/opt/probe-a.sh",), ("/opt/probe-b.sh", "arg")),
        )
        value = card.canonical()
        self.assertEqual(tuple(value["candidate_build"]), ("env", "X=1", "/opt/build.sh"))
        self.assertEqual(
            tuple(tuple(x) for x in value["selfcheck_commands"]),
            (("/opt/probe-a.sh",), ("/opt/probe-b.sh", "arg")),
        )

    def test_defaults_stay_empty(self) -> None:
        card = _minimal_card()
        self.assertEqual(card.candidate_build, ())
        self.assertEqual(card.selfcheck_commands, ())


class CardgenTest(unittest.TestCase):
    def test_cairo_card_is_generic_and_probed(self) -> None:
        from lda_hm.cardgen import generate_card

        reference = json.loads(
            (Path(__file__).resolve().parents[1] / "examples" / "libpng-card.json")
            .read_text(encoding="utf-8")
        )
        card = generate_card("libcairo2", reference["baseline"])
        self.assertEqual(
            card["candidate_build"][-1], "/opt/lda/harness/checks/ensure-pkg-candidate.sh"
        )
        self.assertEqual(
            card["selfcheck_commands"][0][-1],
            "/opt/lda/harness/checks/run-cairo-owned-selfcheck.sh",
        )
        self.assertEqual(
            card["dependency_tests"][0][-2:],
            ["/opt/lda/harness/checks/run-autopkgtest-fence.sh", "candidate"],
        )
        setup_tails = [command[-1] for command in card["setup_commands"]]
        self.assertIn("/opt/lda/harness/checks/install-test-tools.sh", setup_tails)
        self.assertIn("baseline", setup_tails)
        micro = card["micro_benchmarks"][0]
        self.assertEqual(micro["holdout_env"], "LDA_CAIRO_PATHDIR")
        self.assertEqual(micro["holdout_min_speedup_percent"], 1.0)
        self.assertEqual(micro["inputs"], ["stroke-dash", "fill-tess", "text-corpus"])

    def test_unprofiled_package_is_refused(self) -> None:
        from lda_hm.cardgen import generate_card

        reference = json.loads(
            (Path(__file__).resolve().parents[1] / "examples" / "libpng-card.json")
            .read_text(encoding="utf-8")
        )
        with self.assertRaises(SystemExit):
            generate_card("polkitd", reference["baseline"])


if __name__ == "__main__":
    unittest.main()
