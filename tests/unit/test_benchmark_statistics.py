from lda.benchmarks import BenchmarkDecision, BenchmarkSeries, compare_paired, portfolio_decision
from lda.config import BenchmarkConfig


def series(name: str, layer: str, ratio: float) -> BenchmarkSeries:
    baseline = [1.0 + (index % 3) * 0.0001 for index in range(30)]
    candidate = [value / ratio for value in baseline]
    micro_scenarios = [
        "input=16;distribution=sequential;cache=hot;concurrency=1",
        "input=64;distribution=random;cache=cold;concurrency=2",
        "input=16;distribution=random;cache=hot;concurrency=2",
        "input=64;distribution=sequential;cache=cold;concurrency=1",
    ]
    return BenchmarkSeries(
        name=name,
        layer=layer,
        baseline=baseline,
        candidate=candidate,
        warmups=10,
        seed=2604,
        randomized_order=["baseline" if index % 2 else "candidate" for index in range(30)],
        scenario_ids=(
            [micro_scenarios[index % len(micro_scenarios)] for index in range(30)]
            if layer == "micro"
            else [f"workload={name}"] * 30
        ),
        cpu_affinity="0",
        numa_policy="local",
        environment={"cpu": "Xeon 6548Y+"},
    )


def test_micro_requires_speedup_and_ci() -> None:
    config = BenchmarkConfig()
    assert compare_paired(series("win", "micro", 1.05), config, bootstrap_samples=500).decision is BenchmarkDecision.PASS
    assert compare_paired(series("loss", "micro", 1.01), config, bootstrap_samples=500).decision is BenchmarkDecision.FAIL


def test_portfolio_requires_two_e2e_wins() -> None:
    config = BenchmarkConfig()
    comparisons = [
        compare_paired(series("a", "e2e", 1.02), config, bootstrap_samples=500),
        compare_paired(series("b", "e2e", 1.03), config, bootstrap_samples=500),
    ]
    assert portfolio_decision(comparisons, config)


def test_micro_requires_all_scenario_axes() -> None:
    value = series("matrix", "micro", 1.05)
    assert len(value.scenario_ids) == 30
    assert len(set(value.scenario_ids)) == 4


def test_noise_is_measured_within_each_scenario() -> None:
    value = series("heterogeneous", "micro", 1.05)
    scenario_scale = {
        scenario: float(10**index)
        for index, scenario in enumerate(sorted(set(value.scenario_ids)))
    }
    baseline = [
        duration * scenario_scale[scenario]
        for duration, scenario in zip(value.baseline, value.scenario_ids, strict=True)
    ]
    candidate = [duration / 1.05 for duration in baseline]

    comparison = compare_paired(
        value.model_copy(update={"baseline": baseline, "candidate": candidate}),
        BenchmarkConfig(),
        bootstrap_samples=500,
    )

    assert comparison.decision is BenchmarkDecision.PASS
    assert comparison.baseline_cv < 0.01
    assert comparison.candidate_cv < 0.01


def test_noisy_single_scenario_invalidates_the_series() -> None:
    value = series("noisy", "micro", 1.05)
    noisy_scenario = value.scenario_ids[0]
    baseline = list(value.baseline)
    candidate = list(value.candidate)
    noisy_indexes = [
        index
        for index, scenario_id in enumerate(value.scenario_ids)
        if scenario_id == noisy_scenario
    ]
    for offset, index in enumerate(noisy_indexes):
        baseline[index] *= 1.0 if offset % 2 else 2.0
        candidate[index] = baseline[index] / 1.05

    comparison = compare_paired(
        value.model_copy(update={"baseline": baseline, "candidate": candidate}),
        BenchmarkConfig(),
        bootstrap_samples=500,
    )

    assert comparison.decision is BenchmarkDecision.INVALID
    assert comparison.baseline_cv > BenchmarkConfig().max_noise_cv
