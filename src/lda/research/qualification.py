from __future__ import annotations

from typing import Iterable

from lda.models import MissionContract, QualificationRecord, ResearchSnapshot


def build_qualification_records(
    snapshot: ResearchSnapshot,
    packages: Iterable[str],
    *,
    ubuntu_snapshot: str,
) -> list[QualificationRecord]:
    """Create pending records; only E2B evidence may promote them to QUALIFIED."""

    hints = {hint.package: hint for hint in snapshot.hints}
    records: list[QualificationRecord] = []
    for package in packages:
        hint = hints.get(package)
        records.append(
            QualificationRecord(
                package=package,
                snapshot=ubuntu_snapshot,
                evidence_refs=tuple(hint.evidence_sources) if hint else (),
                notes=(
                    "Research ranking is evidence, not package identity.",
                    "Verify apt identity, source rebuild, ABI/API/FFI, Micro and E2E in E2B before promotion.",
                ),
            )
        )
    return records
