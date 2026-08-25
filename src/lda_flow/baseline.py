"""Validation and transport metadata for an exact Ubuntu ISO package baseline."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import yaml
from pydantic import BaseModel, ConfigDict, Field, field_validator

from .models import Campaign, Mission


class BaselineEntry(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    package: str
    version: str = Field(min_length=1)
    architecture: str = "amd64"
    sha256: str = Field(pattern=r"^[0-9a-fA-F]{64}$")
    source_package: str
    source_version: str = Field(min_length=1)
    source_sha256: str | None = Field(default=None, pattern=r"^[0-9a-fA-F]{64}$")
    binary_path: str | None = None

    @field_validator("binary_path")
    @classmethod
    def binary_path_is_relative(cls, value: str | None) -> str | None:
        if value is not None and Path(value).is_absolute():
            raise ValueError("baseline binary_path must be relative to the controller")
        return value


class BaselineLock(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: int = Field(default=1, ge=1)
    origin: str = Field(min_length=8)
    release: str = "26.04"
    architecture: str = "amd64"
    manifest_sha256: str = Field(pattern=r"^[0-9a-fA-F]{64}$")
    packages: dict[str, BaselineEntry]


def load_baseline_lock(campaign: Campaign) -> BaselineLock:
    """Load a lock generated from the ISO parser and validate Mission coverage."""
    manifest = Path(campaign.baseline.manifest_path)
    lock_path = Path(campaign.baseline.lock_path)
    if not manifest.is_file():
        raise FileNotFoundError(f"Ubuntu ISO manifest is missing: {manifest}")
    if not lock_path.is_file():
        raise FileNotFoundError(f"Ubuntu baseline lock is missing: {lock_path}")
    manifest_digest = hashlib.sha256(manifest.read_bytes()).hexdigest()
    lock = BaselineLock.model_validate(yaml.safe_load(lock_path.read_text(encoding="utf-8")))
    if lock.release != campaign.ubuntu_release or lock.architecture != "amd64":
        raise ValueError("baseline lock release or architecture does not match Campaign")
    if lock.manifest_sha256.lower() != manifest_digest:
        raise ValueError("baseline lock does not match the supplied ISO manifest")
    for mission in campaign.missions:
        _validate_mission_entry(mission, lock)
    return lock


def _validate_mission_entry(mission: Mission, lock: BaselineLock) -> BaselineEntry:
    package = mission.package.binary_package
    entry = lock.packages.get(package)
    if entry is None:
        raise ValueError(f"baseline lock has no entry for {package}")
    if entry.package != package or entry.architecture != mission.package.architecture:
        raise ValueError(f"baseline identity mismatch for {package}")
    if entry.source_package != mission.source_package:
        raise ValueError(f"baseline source package mismatch for {package}")
    return entry


def mission_entry(lock: BaselineLock, mission: Mission) -> BaselineEntry:
    return _validate_mission_entry(mission, lock)


def lock_json(entry: BaselineEntry) -> str:
    return json.dumps(entry.model_dump(), sort_keys=True) + "\n"


def lock_summary(lock: BaselineLock) -> dict[str, object]:
    return {
        "origin": lock.origin,
        "release": lock.release,
        "architecture": lock.architecture,
        "manifest_sha256": lock.manifest_sha256,
        "packages": sorted(lock.packages),
    }
