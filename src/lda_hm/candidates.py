"""Ranked Ubuntu 26.04 optimization candidates (dependency-graph top-30).

The ranking is produced offline from the ISO dependency graph and checked in
as data/candidates-ubuntu-2604.json; this module makes the flow actually
consume it: a production card must target the pilot package or a ranked
candidate, so effort follows the priority analysis instead of whim.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Optional


CANDIDATES_FILE = Path(__file__).resolve().parents[2] / "data" / "candidates-ubuntu-2604.json"


@dataclass(frozen=True)
class RankedCandidate:
    package: str
    score: float
    direction: int


def load_candidates(path: Optional[Path] = None) -> tuple[RankedCandidate, ...]:
    source = path or CANDIDATES_FILE
    value = json.loads(source.read_text(encoding="utf-8"))
    ranked = tuple(
        RankedCandidate(
            package=str(entry["package"]),
            score=float(entry["score"]),
            direction=int(entry.get("direction", 0)),
        )
        for entry in value.get("candidates", ())
    )
    if not ranked:
        raise ValueError(f"no candidates found in {source}")
    return tuple(sorted(ranked, key=lambda item: -item.score))


def pilot_package(path: Optional[Path] = None) -> str:
    source = path or CANDIDATES_FILE
    value = json.loads(source.read_text(encoding="utf-8"))
    return str(value.get("pilot", {}).get("package", ""))


def is_sanctioned(package: str, path: Optional[Path] = None) -> bool:
    """A package is sanctioned when it is the pilot or in the ranked top-30.

    Source package names and binary package names both count (libpng1.6 vs
    libpng16-16t64 style differences are matched on a shared prefix).
    """
    normalized = package.strip().lower()
    if not normalized:
        return False
    names = {candidate.package.lower() for candidate in load_candidates(path)}
    pilot = pilot_package(path).lower()
    if pilot:
        names.add(pilot)
    if normalized in names:
        return True
    return any(
        name.startswith(normalized) or normalized.startswith(name.rstrip("0123456789.-"))
        for name in names
    )
