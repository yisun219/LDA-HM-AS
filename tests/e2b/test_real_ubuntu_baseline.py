import os

import pytest
from e2b import AsyncSandbox

from lda.config import LDAConfig
from lda.e2b.shared_gateway import configure_shared_gateway


pytestmark = pytest.mark.skipif(os.getenv("LDA_REAL_E2B") != "1", reason="real E2B test")


async def test_real_ubuntu_2604_libpng_baseline() -> None:
    config = LDAConfig.load()
    config.e2b.apply_public_environment()
    config.e2b.api_key()
    configure_shared_gateway()
    sandbox = await AsyncSandbox.create(
        template=config.e2b.base_template,
        timeout=7200,
        metadata={
            "project": "lda",
            "run_id": "e2b-baseline-smoke",
            "mission_id": "libpng",
            "candidate_id": "",
            "role": "workspace",
            "lease_id": "e2b-baseline-smoke",
            "owner": "lda-controller",
        },
        envs={},
    )
    try:
        result = await sandbox.commands.run(
            "/opt/lda/harness/checks/prepare-mission-baseline.sh "
            "libpng1.6 1.6.57-1 libpng16-16t64=1.6.57-1 libpng-dev=1.6.57-1",
            timeout=5400,
        )
        assert result.exit_code == 0, result.stderr
        verify = await sandbox.commands.run(
            "test \"$(. /etc/os-release; echo $VERSION_ID)\" = 26.04 && "
            "test \"$(lscpu | sed -n 's/^Model:[[:space:]]*//p')\" = 207 && "
            "test -s /opt/lda/baseline/source.tar.bundle && "
            "test \"$(find /opt/lda/baseline -maxdepth 1 -name '*.deb' | wc -l)\" -ge 2 && "
            "git -C /opt/lda/work diff --quiet && git -C /opt/lda/work diff --cached --quiet"
        )
        assert verify.exit_code == 0, verify.stderr
    finally:
        await sandbox.kill()
