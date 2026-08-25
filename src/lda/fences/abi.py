from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class FenceManifest:
    package: str
    soname: str
    symbols: tuple[str, ...] = ()
    symbol_versions: tuple[str, ...] = ()
    headers: tuple[str, ...] = ()
    struct_layouts: dict[str, str] = field(default_factory=dict)
    install_paths: tuple[str, ...] = ()
    dependency_metadata: dict[str, Any] = field(default_factory=dict)


class CompatibilityFence:
    """Immutable compatibility contract. A failed check is never overridable."""

    def __init__(self, manifest: FenceManifest):
        self.manifest = manifest

    def check(self, candidate: dict[str, Any]) -> dict[str, Any]:
        failures: list[str] = []
        for key in ("soname", "symbols", "symbol_versions", "headers", "install_paths"):
            expected = getattr(self.manifest, key)
            actual = candidate.get(key, expected if not expected else None)
            if expected and actual is None:
                failures.append(f"missing {key}")
            elif expected and tuple(actual) != tuple(expected):
                failures.append(f"{key} changed")
        if candidate.get("abidiff", True) is False:
            failures.append("abidiff failed")
        if candidate.get("abi_compliance", True) is False:
            failures.append("abi-compliance-checker failed")
        if candidate.get("header_compile", True) is False:
            failures.append("header compilation failed")
        if candidate.get("calling_convention", True) is False:
            failures.append("calling convention changed")
        if candidate.get("ffi", True) is False:
            failures.append("FFI smoke failed")
        for check in ("pkg_config", "cmake_config", "dlopen_dlsym", "prebuilt_binary",
                      "c_source", "cpp_source", "python_ctypes", "python_cffi", "rust_ffi"):
            if candidate.get(check, True) is False:
                failures.append(f"{check} failed")
        if self.manifest.struct_layouts and candidate.get("struct_layouts", self.manifest.struct_layouts) != self.manifest.struct_layouts:
            failures.append("struct layout changed")
        return {"passed": not failures, "failures": failures, "immutable": True}
