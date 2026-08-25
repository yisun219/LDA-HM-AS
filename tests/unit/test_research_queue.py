from hashlib import sha256
from pathlib import Path

import pytest

from lda.artifacts import ArtifactStore
from lda.packages import InventoryMetrics, freeze_mission_queue
from lda.research import ingest_research


def metric(package: str, value: float) -> InventoryMetrics:
    return InventoryMetrics(
        package=package,
        usage_frequency=value,
        measured_cpu_share=value,
        dependency_centrality=value,
        workload_generality=value,
        expected_effort_efficiency=value,
        compatibility_risk=0.1,
    )


def test_research_snapshot_and_queue_are_frozen(tmp_path: Path) -> None:
    source = tmp_path / "research.json"
    source.write_text(
        '[{"package":"libpng16-16t64","hypothesis":"hot decode path","confidence":0.8},'
        '{"package":"libaio1t64","hypothesis":"submission overhead","confidence":0.7}]',
        encoding="utf-8",
    )
    artifacts = ArtifactStore(tmp_path / "artifacts")
    snapshot = ingest_research([source], artifacts)
    assert len(snapshot.source_artifacts) == 1
    assert snapshot.source_artifacts[0].sha256 == sha256(source.read_bytes()).hexdigest()
    assert artifacts.read_bytes(snapshot.source_artifacts[0].artifact_ref) == source.read_bytes()
    queue = freeze_mission_queue(
        "run",
        snapshot,
        [metric("libpng16-16t64", 0.9), metric("libaio1t64", 0.7)],
        limit=2,
    )
    assert queue.frozen is True
    assert list(queue.missions) == ["libpng16-16t64", "libaio1t64"]
    with pytest.raises(Exception):
        queue.missions.append("other")


def test_queue_rejects_dynamic_duplicates(tmp_path: Path) -> None:
    source = tmp_path / "research.yaml"
    source.write_text("hints:\n  - package: libpng16-16t64\n    hypothesis: hot\n    confidence: 0.5\n", encoding="utf-8")
    snapshot = ingest_research([source], ArtifactStore(tmp_path / "a"))
    first = freeze_mission_queue("run", snapshot, [metric("libpng16-16t64", 0.9)], limit=1)
    second = freeze_mission_queue("run", snapshot, [metric("libpng16-16t64", 0.9)], limit=1)
    assert first.queue_hash == second.queue_hash
