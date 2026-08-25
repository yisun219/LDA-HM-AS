"""Build the pinned E2B lda-base template without embedding credentials."""

from __future__ import annotations

import os
from pathlib import Path

from e2b import Template

INTEL_SKILLS_COMMIT = "e9d0b6410fb1ad7a50fb81e0868fd23ae886882c"

BASE_PACKAGES = [
    "build-essential",
    "clang",
    "llvm",
    "gcc",
    "g++",
    "cmake",
    "meson",
    "ninja-build",
    "devscripts",
    "debhelper",
    "dpkg-dev",
    "fakeroot",
    "sbuild",
    "autopkgtest",
    "abigail-tools",
    "abi-dumper",
    "abi-compliance-checker",
    "universal-ctags",
    "binutils",
    "linux-tools-generic",
    "linux-tools-common",
    "strace",
    "valgrind",
    "fio",
    "imagemagick",
    "wrk",
    "xvfb",
    "chromium",
    "python3",
    "python3-pip",
    "nodejs",
    "npm",
    "git",
    "curl",
    "wget",
    "ca-certificates",
    "pkg-config",
]


def build() -> None:
    template = Template(file_context_path=Path(__file__).parents[2]).from_image("ubuntu:26.04")
    template = template.apt_install(BASE_PACKAGES)
    template = template.run_cmd(
        "python3 -m pip install --no-cache-dir 'pydantic>=2.9,<3' PyYAML 'e2b==2.15.0'"
    )
    template = template.run_cmd("npm install --global @openai/codex")
    template = template.run_cmd(
        "git clone https://github.com/intel/intel-performance-skills.git "
        "/opt/intel-performance-skills && cd /opt/intel-performance-skills && "
        f"git checkout {INTEL_SKILLS_COMMIT} && "
        "test -f skills/linux-perf/SKILL.md && "
        "test -f skills/performance-patterns/SKILL.md && "
        "test -f skills/phoronix-test-suite/SKILL.md"
    )
    template = template.copy(
        ["pyproject.toml", "src", "flows", "validation"], "/opt/lda"
    )
    template = template.run_cmd("python3 -m pip install --no-cache-dir /opt/lda")
    template = template.run_cmd(
        "command -v lda-flow && command -v hmz && "
        "test -f /opt/lda/flows/lda/__init__.py"
    )
    template = template.run_cmd(
        "test -r /etc/os-release && grep -q 'VERSION_ID=\"26.04\"' /etc/os-release"
    )
    template = template.run_cmd("mkdir -p /opt/lda /workspace/mission /workspace/.lda")
    Template.build(template, name=os.getenv("E2B_TEMPLATE", "lda-base"))


if __name__ == "__main__":
    build()
