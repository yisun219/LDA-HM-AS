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
