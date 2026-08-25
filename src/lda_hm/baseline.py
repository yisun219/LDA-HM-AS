from __future__ import annotations

import hashlib
import json
import re
from dataclasses import asdict, dataclass
from typing import Any


_SHA256 = re.compile(r"^[0-9a-fA-F]{64}$")


@dataclass(frozen=True)
class BaselineSpec:
    """Immutable identity and verification contract for one execution base."""

    mode: str = "source_package"
    template: str = "lda-base"
    release: str = "26.04"
    codename: str = "resolute"
    edition: str = "generic"
    architecture: str = "amd64"
    metadata_path: str = "/opt/lda/baseline/baseline.json"
    manifest_path: str = "/opt/lda/baseline/manifest/debian-packages.tsv"
    snap_manifest_path: str = "/opt/lda/baseline/manifest/snaps.tsv"
    iso_artifact: str = ""
    iso_sha256: str = ""
    iso_build_id: str = ""
    manifest_sha256: str = ""
    snap_manifest_sha256: str = ""
    apt_snapshot: str = ""
    rootfs_digest: str = ""
    package_inventory_digest: str = ""
    snap_inventory_digest: str = ""

    def __post_init__(self) -> None:
        if self.mode not in {"source_package", "iso_snapshot"}:
            raise ValueError("baseline mode must be source_package or iso_snapshot")
        if not self.template.strip():
            raise ValueError("baseline template must not be empty")
        if self.release != "26.04" or self.codename != "resolute":
            raise ValueError("LDA currently supports Ubuntu 26.04 resolute only")
        if self.architecture != "amd64":
            raise ValueError("LDA currently supports amd64 baseline execution only")
        if self.mode == "iso_snapshot":
            if self.edition != "desktop":
                raise ValueError("iso_snapshot baseline must be Ubuntu Desktop")
            for name in (
                "iso_artifact",
                "iso_sha256",
                "iso_build_id",
                "manifest_sha256",
                "snap_manifest_sha256",
                "apt_snapshot",
                "rootfs_digest",
                "package_inventory_digest",
                "snap_inventory_digest",
            ):
                value = getattr(self, name)
                if not value.strip():
                    raise ValueError(f"iso_snapshot baseline requires {name}")
                if name.endswith("sha256") and not _SHA256.fullmatch(value):
                    raise ValueError(f"{name} must be a SHA256 digest")

    @property
    def is_distribution(self) -> bool:
        return self.mode == "iso_snapshot"

    def canonical(self) -> dict[str, Any]:
        return asdict(self)

    def digest(self) -> str:
        encoded = json.dumps(self.canonical(), sort_keys=True, separators=(",", ":")).encode()
        return hashlib.sha256(encoded).hexdigest()

    def verification_command(self) -> tuple[str, ...]:
        env = {
            "LDA_BASELINE_MODE": self.mode,
            "LDA_BASELINE_RELEASE": self.release,
            "LDA_BASELINE_CODENAME": self.codename,
            "LDA_BASELINE_EDITION": self.edition,
            "LDA_BASELINE_ARCH": self.architecture,
            "LDA_BASELINE_METADATA_PATH": self.metadata_path,
            "LDA_BASELINE_MANIFEST_PATH": self.manifest_path,
            "LDA_BASELINE_SNAP_MANIFEST_PATH": self.snap_manifest_path,
            "LDA_BASELINE_ISO_SHA256": self.iso_sha256,
            "LDA_BASELINE_ISO_BUILD_ID": self.iso_build_id,
            "LDA_BASELINE_MANIFEST_SHA256": self.manifest_sha256,
            "LDA_BASELINE_SNAP_MANIFEST_SHA256": self.snap_manifest_sha256,
            "LDA_BASELINE_APT_SNAPSHOT": self.apt_snapshot,
            "LDA_BASELINE_ROOTFS_DIGEST": self.rootfs_digest,
            "LDA_BASELINE_PACKAGE_INVENTORY_DIGEST": self.package_inventory_digest,
            "LDA_BASELINE_SNAP_INVENTORY_DIGEST": self.snap_inventory_digest,
        }
        return (
            "env",
            *(f"{key}={value}" for key, value in env.items()),
            "/opt/lda/harness/checks/verify-baseline.sh",
        )
