"""Deterministic release gates between qualification and execution.

Qualification is allowed to produce partial facts for every report candidate.  The
controller may enter a mission only when the canary rows contain explicit,
auditable evidence for every hard gate.  This module deliberately does not
derive or manufacture performance values.
"""

from __future__ import annotations

from typing import Any, Iterable


REQUIRED_QUALIFICATION_GATES: tuple[tuple[str, str], ...] = (
    ("source_snapshot_verified", "fixed Sources Snapshot verification"),
    ("source_unpacked_verified", "source unpack"),
    ("clean_source_rebuild_verified", "clean source rebuild"),
)

# These gates are intentionally not needed to start the fixed LDA Mission.
# They are produced by the inner mission and deterministic Judge and required for
# final canary release / Top-10 expansion.
REQUIRED_FINAL_GATES: tuple[tuple[str, str], ...] = (
    ("source_snapshot_verified", "fixed Sources Snapshot verification"),
    ("unresolved_edges_verified", "unresolved edge verification"),
    ("source_unpacked_verified", "source unpack"),
    ("clean_source_rebuild_verified", "clean source rebuild"),
    ("hotspot_verified", "stable hotspot profile"),
    ("micro_benchmark_verified", "micro benchmark"),
    ("e2e_verified", "portfolio E2E"),
    ("deb_replace_verified", ".deb replacement"),
    ("rollback_verified", "rollback verification"),
)
# Backwards-compatible name for callers that used the pre-split gate list.
REQUIRED_CANARY_GATES = REQUIRED_FINAL_GATES


def _verified(row: dict[str, Any], name: str) -> bool:
    """Read a gate without interpreting measurements.

    Producers may use either a boolean plus ``<name>_evidence_refs`` or the
    structured ``{verified, evidence_refs}`` form.  A true value without an
    audit reference is rejected so a model cannot assert a gate by fiat.
    """

    value = row.get(name)
    # Older qualification artifacts used ``source_unpack_verified`` while
    # the public gate name is ``source_unpacked_verified``.  Accept the
    # legacy spelling only when it carries the same explicit evidence refs.
    if value is None and name == "source_unpacked_verified":
        value = row.get("source_unpack_verified")
    refs: Any = row.get(f"{name}_evidence_refs")
    if refs is None and name == "source_unpacked_verified":
        refs = row.get("source_unpack_verified_evidence_refs")
    if isinstance(value, dict):
        verified = value.get("verified") is True
        refs = value.get("evidence_refs", refs)
    else:
        verified = value is True
    if not verified:
        return False
    if refs is None:
        refs = row.get("evidence_refs", [])
    return isinstance(refs, (list, tuple)) and bool(refs)


def _package_row(qualification: dict[str, Any], package: str) -> dict[str, Any] | None:
    for row in qualification.get("results", []):
        if row.get("package") == package:
            return row
    return None


def evaluate_canary_release(qualification: dict[str, Any], canary: Iterable[str]) -> dict[str, Any]:
    """Return the only authorization needed to start canary missions.

    The returned ``eligible_packages`` is exactly the canary set when all gates
    pass and empty otherwise.  Top-10 expansion is intentionally handled only
    after successful LDA Mission/Judge outcomes by :class:`ArgusSupervisor`.
    """

    canary_packages = list(dict.fromkeys(canary))
    package_results: list[dict[str, Any]] = []
    blockers: list[str] = []
    for package in canary_packages:
        row = _package_row(qualification, package)
        missing: list[str] = []
        if row is None:
            missing.append("qualification result")
        else:
            checks = row.get("checks", {})
            for check_name in ("binary_package", "source_mapping", "dependency_metadata", "build_tools"):
                if not isinstance(checks.get(check_name), dict) or checks[check_name].get("available") is not True:
                    missing.append(check_name)
            for gate_name, label in REQUIRED_QUALIFICATION_GATES:
                if not _verified(row, gate_name):
                    missing.append(label)
        package_results.append({"package": package, "ready": not missing, "missing": missing})
        blockers.extend(f"{package}: {item}" for item in missing)
    ready = bool(canary_packages) and not blockers
    return {
        "canary_packages": canary_packages,
        "canary_results": package_results,
        "canary_release_ready": ready,
        "eligible_packages": canary_packages if ready else [],
        "release_blockers": blockers,
        "status": "CANARY_READY" if ready else "QUALIFICATION_PENDING",
    }


def evaluate_final_canary_release(qualification: dict[str, Any], canary: Iterable[str]) -> dict[str, Any]:
    """Evaluate all hard gates for an already executed canary.

    This is separate from :func:`evaluate_canary_release` because measured
    performance and replacement/rollback evidence do not exist until the
    fixed LDA Mission and clean Judge have run.
    """

    packages = list(dict.fromkeys(canary))
    results: list[dict[str, Any]] = []
    blockers: list[str] = []
    for package in packages:
        row = _package_row(qualification, package) or {}
        missing = [label for name, label in REQUIRED_FINAL_GATES if not _verified(row, name)]
        results.append({"package": package, "ready": not missing, "missing": missing})
        blockers.extend(f"{package}: {item}" for item in missing)
    ready = bool(packages) and not blockers
    return {"canary_packages": packages, "canary_results": results,
            "canary_release_ready": ready, "release_blockers": blockers,
            "status": "CANARY_READY" if ready else "QUALIFICATION_PENDING"}
