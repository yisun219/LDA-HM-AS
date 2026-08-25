from __future__ import annotations

import json
import re
from hashlib import sha256
from pathlib import Path
from uuid import uuid4

import yaml

from lda.artifacts import ArtifactStore
from lda.models import ResearchHint, ResearchSnapshot, ResearchSourceArtifact, stable_digest


PACKAGE_PATTERN = re.compile(r"\b(?:lib[a-z0-9][a-z0-9+.-]*|[a-z0-9][a-z0-9+.-]+(?:-common|-core|-daemon))\b")
CAMPAIGN_PACKAGES = frozenset({
    "libgtk-4-1", "libgtk-3-0t64", "gnome-shell", "libreoffice-core",
    "sssd-common", "libcairo2", "gnome-settings-daemon",
    "gstreamer1.0-plugins-good", "ibus", "libsoup-3.0-0",
    "libpng16-16t64", "libaio1t64", "libtiff6", "libheif1",
})


def _structured_hints(path: Path, content: str, source_hash: str) -> list[ResearchHint]:
    try:
        if path.suffix.lower() == ".json":
            value = json.loads(content)
        elif path.suffix.lower() in {".yaml", ".yml"}:
            value = yaml.safe_load(content)
        else:
            return []
    except (ValueError, TypeError):
        return []
    if isinstance(value, dict):
        value = value.get("hints", [value])
    if not isinstance(value, list):
        return []
    hints: list[ResearchHint] = []
    for item in value:
        if not isinstance(item, dict) or not item.get("package"):
            continue
        normalized = {
            "package": item["package"],
            "target_path": item.get("target_path", item.get("target_function", "")),
            "performance_hypothesis": item.get("performance_hypothesis", item.get("hypothesis", "Unverified optimization opportunity")),
            "optimization_approach": item.get("optimization_approach", item.get("approach", "")),
            "workloads": item.get("workloads", []),
            "cpu_features": item.get("cpu_features", []),
            "risks": item.get("risks", []),
            "evidence_sources": item.get("evidence_sources", [str(path)]),
            "confidence": item.get("confidence", 0.5),
            "source_hash": source_hash,
        }
        hints.append(ResearchHint.model_validate(normalized))
    return hints


def _text_hints(path: Path, content: str, source_hash: str) -> list[ResearchHint]:
    packages = sorted(set(PACKAGE_PATTERN.findall(content.lower())) & CAMPAIGN_PACKAGES)
    explicit = {
        package for package in CAMPAIGN_PACKAGES
        if re.search(rf"(?<![a-z0-9+.-]){re.escape(package)}(?![a-z0-9+.-])", content.lower())
    }
    packages = sorted(set(packages) | explicit)
    return [
        ResearchHint(
            package=package,
            performance_hypothesis="Research source names this package as a possible system optimization target; profile evidence is required.",
            workloads=[],
            risks=["unverified research hint", "ABI/API/FFI compatibility"],
            evidence_sources=[str(path)],
            confidence=0.35,
            source_hash=source_hash,
        )
        for package in packages
    ]


def ingest_research(paths: list[Path], artifacts: ArtifactStore) -> ResearchSnapshot:
    files: list[Path] = []
    for path in paths:
        resolved = path.resolve()
        if resolved.is_dir():
            files.extend(item for item in sorted(resolved.rglob("*")) if item.is_file())
        elif resolved.is_file():
            files.append(resolved)
        else:
            raise FileNotFoundError(path)
    if not files:
        raise ValueError("research ingest requires at least one file")
    hints: list[ResearchHint] = []
    source_files: list[str] = []
    source_artifacts: list[ResearchSourceArtifact] = []
    aggregate = sha256()
    for path in files:
        content_bytes = path.read_bytes()
        source_hash = sha256(content_bytes).hexdigest()
        artifact_ref = artifacts.put_bytes(content_bytes)
        if artifact_ref != source_hash:
            raise RuntimeError("research source artifact digest mismatch")
        artifacts.set_ref(f"research/sources/{source_hash}", artifact_ref)
        aggregate.update(path.name.encode())
        aggregate.update(content_bytes)
        source_files.append(str(path))
        source_artifacts.append(ResearchSourceArtifact(
            file_name=path.name,
            original_path=str(path),
            sha256=source_hash,
            artifact_ref=artifact_ref,
            size_bytes=len(content_bytes),
        ))
        content = content_bytes.decode("utf-8", errors="replace")
        parsed = _structured_hints(path, content, source_hash)
        hints.extend(parsed or _text_hints(path, content, source_hash))
    if not hints:
        raise ValueError("research files contain no package hints")
    deduplicated: dict[tuple[str, str, str], ResearchHint] = {}
    for hint in hints:
        deduplicated[(hint.package, hint.target_path, hint.performance_hypothesis)] = hint
    snapshot = ResearchSnapshot(
        snapshot_id=f"research-{uuid4().hex}",
        source_files=source_files,
        source_artifacts=source_artifacts,
        hints=list(deduplicated.values()),
        content_hash=aggregate.hexdigest(),
    )
    digest = artifacts.put_json(snapshot)
    artifacts.set_ref(f"research/{snapshot.snapshot_id}.json", digest)
    sealed = ResearchSnapshot.model_validate(artifacts.read_json(digest))
    if stable_digest(sealed) != stable_digest(snapshot):
        raise RuntimeError("research snapshot verification failed")
    return snapshot
