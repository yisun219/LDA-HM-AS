from __future__ import annotations

from pathlib import Path

import yaml

from lda.controller.engine import mission_execution_waves
from lda.controller.request import MissionDefinition


TOP_10 = [
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
]

ISO_VERSIONS = {
    "libgtk-4-1": "4.22.2+ds-1ubuntu1",
    "libgtk-3-0t64": "3.24.52-0ubuntu1",
    "gnome-shell": "50.1-0ubuntu1",
    "libreoffice-core": "4:26.2.2.2-0ubuntu1",
    "sssd-common": "2.12.0-1ubuntu5",
    "libcairo2": "1.18.4-3",
    "gnome-settings-daemon": "50.0-1ubuntu1",
    "gstreamer1.0-plugins-good": "1.28.2-2",
    "ibus": "1.5.34~rc2-1",
    "libsoup-3.0-0": "3.6.6-1",
}


def _definitions() -> dict[str, MissionDefinition]:
    definitions: dict[str, MissionDefinition] = {}
    for path in Path("configs/missions").glob("*.yaml"):
        definition = MissionDefinition.model_validate(
            yaml.safe_load(path.read_text(encoding="utf-8"))
        )
        definitions[definition.package] = definition
    return definitions


def test_top10_has_executable_mission_definitions_at_iso_versions() -> None:
    campaign = yaml.safe_load(Path("configs/campaign-top10.yaml").read_text(encoding="utf-8"))
    definitions = _definitions()

    assert campaign["packages"] == TOP_10
    for package, version in ISO_VERSIONS.items():
        definition = definitions[package]
        assert definition.source_version == version
        assert definition.baseline_commands
        assert definition.profile_commands
        assert definition.local_verify_commands
        assert definition.judge_manifest is not None


def test_canaries_complete_before_remaining_top10() -> None:
    frozen_priority_order = [
        "libcairo2",
        "libsoup-3.0-0",
        "libgtk-4-1",
        "libgtk-3-0t64",
        "gstreamer1.0-plugins-good",
        "ibus",
        "libreoffice-core",
        "gnome-shell",
        "gnome-settings-daemon",
        "sssd-common",
    ]

    canaries, remaining = mission_execution_waves(frozen_priority_order)

    assert canaries == ["libcairo2", "libsoup-3.0-0"]
    assert set(canaries + remaining) == set(TOP_10)
    assert not set(canaries) & set(remaining)


def test_canary_micro_probes_consume_scenario_inputs() -> None:
    definitions = _definitions()
    for package in ("libcairo2", "libsoup-3.0-0"):
        body = definitions[package].probe_body
        assert "input_size" in body
        assert "distribution" in body or package == "libcairo2"
