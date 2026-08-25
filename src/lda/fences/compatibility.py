from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field


class CompatibilityStatus(StrEnum):
    PASS = "PASS"
    FAIL = "FAIL"
    NOT_RUN = "NOT_RUN"


class FenceCheck(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    name: str
    status: CompatibilityStatus
    command: str
    stdout_ref: str
    stderr_ref: str


class CompatibilityReport(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    soname: FenceCheck
    exported_symbols: FenceCheck
    symbol_versions: FenceCheck
    abidiff: FenceCheck
    abi_compliance_checker: FenceCheck
    header_compile: FenceCheck
    struct_layout: FenceCheck
    calling_convention: FenceCheck
    pkg_config: FenceCheck
    cmake_config: FenceCheck
    install_paths: FenceCheck
    precompiled_binary: FenceCheck
    python_ctypes: FenceCheck
    python_cffi: FenceCheck
    rust_ffi: FenceCheck
    dlopen_dlsym: FenceCheck
    c_cpp_source: FenceCheck
    debian_relationships: FenceCheck

    @property
    def passed(self) -> bool:
        return all(value.status is CompatibilityStatus.PASS for value in self.__dict__.values())
