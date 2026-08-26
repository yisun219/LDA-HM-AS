from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path
from typing import Any


SCHEMA = "lda.portfolio-e2e.v1"
WORKLOAD_KINDS = frozenset({"web_server", "chrome_gui"})
SECRET_MARKERS = ("KEY", "TOKEN", "SECRET", "PASSWORD", "CREDENTIAL")


def validate_config(raw: dict[str, Any]) -> dict[str, Any]:
    """Validate a bounded, local-only portfolio workload configuration."""
    if not isinstance(raw, dict):
        raise ValueError("portfolio config must be an object")
    warmups = raw.get("warmups", 2)
    samples = raw.get("samples", 5)
    if not isinstance(warmups, int) or not 0 <= warmups <= 20:
        raise ValueError("warmups must be an integer between 0 and 20")
    if not isinstance(samples, int) or not 2 <= samples <= 50:
        raise ValueError("samples must be an integer between 2 and 50")
    variants: dict[str, dict[str, Any]] = {}
    for name in ("baseline", "candidate"):
        value = raw.get(name)
        if not isinstance(value, dict):
            raise ValueError(f"{name} must be an object")
        document_root = Path(value.get("document_root", "")).resolve()
        if not document_root.is_dir():
            raise ValueError(f"{name}.document_root must exist")
        env = value.get("env", {})
        if not isinstance(env, dict) or any(not isinstance(k, str) or not isinstance(v, str) for k, v in env.items()):
            raise ValueError(f"{name}.env must contain string values")
        if any(any(marker in key.upper() for marker in SECRET_MARKERS) for key in env):
            raise ValueError(f"{name}.env contains a forbidden secret-like key")
        if set(env) - {"LD_LIBRARY_PATH"}:
            raise ValueError(f"{name}.env may only set LD_LIBRARY_PATH")
        variants[name] = {"document_root": str(document_root), "env": dict(env)}
    workloads = raw.get("workloads")
    if not isinstance(workloads, list) or len(workloads) < 2:
        raise ValueError("at least two workloads are required")
    normalized = []
    names = set()
    kinds = set()
    for item in workloads:
        if not isinstance(item, dict):
            raise ValueError("workload must be an object")
        name, kind = item.get("name"), item.get("kind")
        if not isinstance(name, str) or not name or name in names:
            raise ValueError("workload names must be unique non-empty strings")
        if kind not in WORKLOAD_KINDS:
            raise ValueError(f"unsupported workload kind: {kind}")
        path = item.get("path", "/index.html")
        if not isinstance(path, str) or not path.startswith("/") or "://" in path:
            raise ValueError("workload path must be a local absolute URL path")
        iterations = item.get("iterations", 3)
        if not isinstance(iterations, int) or not 1 <= iterations <= 100:
            raise ValueError("iterations must be between 1 and 100")
        normalized.append({"name": name, "kind": kind, "path": path, "iterations": iterations})
        names.add(name); kinds.add(kind)
    if len(kinds) < 2:
        raise ValueError("portfolio must cover at least two workload kinds")
    return {"schema": SCHEMA, "warmups": warmups, "samples": samples,
            "baseline": variants["baseline"], "candidate": variants["candidate"],
            "workloads": normalized}


def config_hash(config: dict[str, Any]) -> str:
    return hashlib.sha256(json.dumps(config, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def parse_result(output: str, *, expected_config_hash: str | None = None) -> dict[str, Any]:
    """Parse harness JSON and reject missing/raw-less or internally inconsistent evidence."""
    try:
        payload = json.loads(output)
    except (TypeError, json.JSONDecodeError) as exc:
        return _invalid(f"invalid_json:{exc}")
    if not isinstance(payload, dict) or payload.get("schema") != SCHEMA:
        return _invalid("invalid_schema")
    if expected_config_hash and payload.get("config_sha256") != expected_config_hash:
        return _invalid("config_hash_mismatch")
    raw = payload.get("raw_workloads")
    speeds = payload.get("workloads")
    metadata = payload.get("metadata")
    if not isinstance(metadata, dict) or metadata.get("network_scope") != "loopback-only":
        return _invalid("network_scope_not_verified")
    if not isinstance(raw, dict) or not isinstance(speeds, dict) or set(raw) != set(speeds) or len(raw) < 2:
        return _invalid("missing_or_mismatched_workloads")
    checked: dict[str, float] = {}
    for name, evidence in raw.items():
        if not isinstance(evidence, dict) or evidence.get("kind") not in WORKLOAD_KINDS:
            return _invalid(f"invalid_workload:{name}")
        baseline, candidate = evidence.get("baseline"), evidence.get("candidate")
        if not isinstance(baseline, list) or not isinstance(candidate, list) or len(baseline) < 2 or len(baseline) != len(candidate):
            return _invalid(f"invalid_samples:{name}")
        if any(not isinstance(x, (int, float)) or x <= 0 for x in baseline + candidate):
            return _invalid(f"nonpositive_samples:{name}")
        if evidence.get("samples") not in (None, len(baseline)):
            return _invalid(f"sample_count_mismatch:{name}")
        measured = sum(baseline) / len(baseline) / (sum(candidate) / len(candidate))
        claimed = speeds.get(name)
        if not isinstance(claimed, (int, float)) or not math.isclose(measured, claimed, rel_tol=1e-9, abs_tol=1e-12):
            return _invalid(f"speedup_mismatch:{name}")
        checked[name] = float(measured)
    geomean = math.prod(checked.values()) ** (1 / len(checked))
    claimed_geomean = payload.get("geomean_speedup")
    if not isinstance(claimed_geomean, (int, float)) or not math.isclose(geomean, claimed_geomean, rel_tol=1e-9, abs_tol=1e-12):
        return _invalid("geomean_mismatch")
    return {"invalid": False, "schema": SCHEMA, "config_sha256": payload.get("config_sha256"),
            "workloads": checked, "raw_workloads": raw, "geomean_speedup": geomean,
            "improved_workloads": sum(value > 1.0 for value in checked.values()),
            "metadata": metadata, "evidence": payload}


def _invalid(reason: str) -> dict[str, Any]:
    return {"invalid": True, "reason": reason, "workloads": {}, "raw_workloads": {},
            "geomean_speedup": 0.0, "improved_workloads": 0}


__all__ = ["SCHEMA", "WORKLOAD_KINDS", "config_hash", "parse_result", "validate_config"]
