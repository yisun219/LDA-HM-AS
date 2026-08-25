import json
import os

import pytest
from e2b import AsyncSandbox

from lda.benchmarks import BenchmarkDecision, BenchmarkSeries, compare_paired
from lda.config import LDAConfig
from lda.e2b.shared_gateway import configure_shared_gateway


pytestmark = pytest.mark.skipif(os.getenv("LDA_REAL_E2B") != "1", reason="real E2B test")


async def test_controlled_package_build_fence_and_benchmark() -> None:
    config = LDAConfig.load()
    config.e2b.apply_public_environment()
    config.e2b.api_key()
    configure_shared_gateway()
    sandbox = await AsyncSandbox.create(template=config.e2b.judge_template, timeout=3600, metadata={
        "project": "lda", "run_id": "fixture-e2e", "mission_id": "fixture",
        "candidate_id": "optimized", "role": "judge", "lease_id": "fixture-e2e", "owner": "lda-controller",
    }, envs={})
    try:
        setup = await sandbox.commands.run(
            "rm -rf /opt/lda/work && cp -a /opt/lda/fixtures/controlled-package /opt/lda/work && "
            "cd /opt/lda/work && git init -b baseline && git -c user.name=LDA -c user.email=lda@localhost add -A && "
            "git -c user.name=LDA -c user.email=lda@localhost commit -m baseline && "
            "tar -C /opt/lda -czf /opt/lda/baseline/source.tar.gz work && "
            "/opt/lda/harness/checks/build-generic-package.sh baseline liblda-fixture1,liblda-fixture-dev && "
            "cp /opt/lda/baseline/packages/*.deb /opt/lda/baseline/ && "
            "/opt/lda/harness/checks/prepare-generic-probe.sh lda_fixture.h 'sink ^= lda_accumulate(1000);' '-llda-fixture' && "
            "git apply /opt/lda/fixtures/controlled-package/optimized.patch && git add -A && "
            "git -c user.name=LDA -c user.email=lda@localhost commit -m optimized && "
            "/opt/lda/harness/checks/build-generic-package.sh candidate liblda-fixture1,liblda-fixture-dev",
            timeout=2400,
        )
        assert setup.exit_code == 0, setup.stderr
        for check in ("soname", "exported-symbols", "symbol-versions", "abidiff", "header-compile", "struct-layout", "calling-convention", "pkg-config", "cmake-config", "install-paths", "precompiled-binary", "debian-relationships"):
            command = [
                "env", "LDA_PUBLIC_HEADER=lda_fixture.h",
                'LDA_LAYOUT_BODY=printf("%zu %zu\\n",sizeof(struct lda_fixture_state),_Alignof(struct lda_fixture_state));',
                "/opt/lda/harness/checks/run-generic-compatibility-check.sh", check,
            ]
            result = await sandbox.commands.run(" ".join(f"'{part}'" for part in command), timeout=600)
            assert result.exit_code == 0, f"{check}: {result.stderr}"
        benchmark = await sandbox.commands.run(
            "/opt/lda/harness/checks/run-paired-probe-benchmark.py --layer micro --name fixture --loops 100000",
            timeout=1200,
        )
        assert benchmark.exit_code == 0, benchmark.stderr
        comparison = compare_paired(BenchmarkSeries.model_validate(json.loads(benchmark.stdout)), config.benchmark)
        assert comparison.decision is BenchmarkDecision.PASS
    finally:
        await sandbox.kill()
