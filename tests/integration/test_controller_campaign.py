from __future__ import annotations

import asyncio
from hashlib import sha256
from pathlib import Path
from types import SimpleNamespace

import yaml

from lda.config import LDAConfig
from lda.controller import engine as engine_module
from lda.controller.engine import CANARY_PACKAGES, PureHumanizeController
from lda.controller.request import MissionDefinition, RunRequest
from lda.models import (
    MissionPhase,
    ResearchHint,
    ResearchSnapshot,
    ResearchSourceArtifact,
    RunPhase,
)
from lda.packages import InventoryMetrics


TOP_10 = (
    "libgtk-4-1",
    "libgtk-3-0t64",
    "gnome-shell",
    "libreoffice-core",
    "sssd-common",
    "libcairo2",
    "gnome-settings-daemon",
    "gstreamer1.0-plugins-good",
    "ibus",
    "libsoup-3.0-0",
)


def _definitions() -> dict[str, MissionDefinition]:
    definitions: dict[str, MissionDefinition] = {}
    for path in Path("configs/missions").glob("*.yaml"):
        definition = MissionDefinition.model_validate(
            yaml.safe_load(path.read_text(encoding="utf-8"))
        )
        definitions[definition.package] = definition
    return definitions


def _request(source_digest: str) -> RunRequest:
    snapshot = ResearchSnapshot(
        snapshot_id="research-controller-integration",
        source_files=("research.md",),
        source_artifacts=(
            ResearchSourceArtifact(
                file_name="research.md",
                original_path="/input/research.md",
                sha256=source_digest,
                artifact_ref=source_digest,
                size_bytes=len(b"frozen research"),
            ),
        ),
        hints=tuple(
            ResearchHint(
                package=package,
                target_path="qualification",
                performance_hypothesis="must be measured in E2B",
                workloads=["controlled"],
                confidence=0.5,
                source_hash=source_digest,
            )
            for package in TOP_10
        ),
        content_hash=source_digest,
    )
    inventory = [
        InventoryMetrics(
            package=package,
            usage_frequency=1.0 - index * 0.01,
            measured_cpu_share=0.9,
            dependency_centrality=0.8,
            workload_generality=0.7,
            expected_effort_efficiency=0.6,
            compatibility_risk=0.2,
        )
        for index, package in enumerate(TOP_10)
    ]
    return RunRequest(
        run_id="run-controller-integration",
        research_snapshot=snapshot,
        inventory=inventory,
        mission_definitions=_definitions(),
        queue_limit=10,
        agent_backend="fake",
        agent_model="fake",
    )


async def test_controller_freezes_and_terminates_all_top10_after_canaries(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setenv("E2B_API_KEY", "e2b_test-only")
    monkeypatch.setenv("LDA_CAPABILITY_SIGNING_KEY", "x" * 32)
    monkeypatch.setenv("LDA_CONTROLLER_SANDBOX_ID", "controller-test")

    async def preflight(_config):
        return SimpleNamespace(to_json=lambda: "{}")

    monkeypatch.setattr(engine_module, "run_preflight", preflight)
    controller = PureHumanizeController(_request(sha256(b"frozen research").hexdigest()), LDAConfig(), tmp_path)
    controller.artifacts.put_bytes(b"frozen research")

    async def start_gateway() -> str:
        return "https://gateway.test"

    async def advisory_agent(state, *, role, **_kwargs) -> str:
        return controller.artifacts.put_json({"role": role, "run_id": state.run_id})

    execution: list[tuple[str, str]] = []

    async def run_mission(state, package: str, _definition) -> None:
        execution.append(("start", package))
        await asyncio.sleep(0)
        state.missions[package].phase = MissionPhase.NOT_HOT
        execution.append(("end", package))

    async def portfolio_e2e(_state) -> bool:
        execution.append(("portfolio", "all"))
        return False

    monkeypatch.setattr(controller, "_start_gateway", start_gateway)
    monkeypatch.setattr(controller, "_advisory_agent", advisory_agent)
    monkeypatch.setattr(controller, "_run_mission", run_mission)
    monkeypatch.setattr(controller, "_portfolio_e2e", portfolio_e2e)

    state = await controller.run()

    assert state.phase is RunPhase.COMPLETED_WITHOUT_RELEASE
    assert set(state.missions) == set(TOP_10)
    assert all(mission.phase is MissionPhase.NOT_HOT for mission in state.missions.values())
    assert execution[-1] == ("portfolio", "all")

    canary_end = max(execution.index(("end", package)) for package in CANARY_PACKAGES)
    first_remaining_start = min(
        execution.index(("start", package))
        for package in TOP_10
        if package not in CANARY_PACKAGES
    )
    assert canary_end < first_remaining_start
