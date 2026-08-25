"""Build the pinned E2B lda-base template without embedding credentials."""

from __future__ import annotations

import json
import os

from e2b import Template

from lda_flow.gateway import concise_e2b_error, configure_shared_gateway

INTEL_SKILLS_COMMIT = "e9d0b6410fb1ad7a50fb81e0868fd23ae886882c"
LDA_COMMIT = "651a9dc"
DEFAULT_TEMPLATE = "lda-base-lda-hm-as"

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
    "python3-venv",
    "python3-pip",
    "nodejs",
    "npm",
    "git",
    "curl",
    "wget",
    "ca-certificates",
    "pkg-config",
]


def _patch_gateway_step_parser() -> None:
    """Keep SDK error reporting usable when the Gateway returns step text."""
    from e2b.template_sync import build_api

    original = build_api.get_build_step_index

    def safe_step_index(step: object, stack_trace_count: int) -> int:
        try:
            return original(step, stack_trace_count)
        except (TypeError, ValueError):
            return 0

    build_api.get_build_step_index = safe_step_index


def build() -> None:
    configure_shared_gateway()
    _patch_gateway_step_parser()
    template = Template().from_image("ubuntu:26.04")
    template = template.apt_install(BASE_PACKAGES)
    template = template.run_cmd(
        "python3 -m venv /opt/lda-venv && "
        "/opt/lda-venv/bin/pip install --no-cache-dir "
        "'pydantic>=2.9,<3' PyYAML 'e2b==2.15.0'"
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
    template = template.run_cmd(
        "git clone https://github.com/yisun219/Linux-Development-Agent-Flow.git "
        "/opt/lda && cd /opt/lda && git checkout " + LDA_COMMIT
    )
    template = template.run_cmd(
        "/opt/lda-venv/bin/pip install --no-cache-dir /opt/lda && "
        "ln -sf /opt/lda-venv/bin/lda-flow /usr/local/bin/lda-flow && "
        "ln -sf /opt/lda-venv/bin/hmz /usr/local/bin/hmz"
    )
    template = template.run_cmd(
        "command -v lda-flow && command -v hmz && "
        "test -f /opt/lda/flows/lda/__init__.py"
    )
    template = template.run_cmd(
        "test -r /etc/os-release && grep -q 'VERSION_ID=\"26.04\"' /etc/os-release"
    )
    template = template.run_cmd(
        "mkdir -p /opt/lda /workspace/mission /workspace/mission/.lda /workspace/.lda"
    )
    name = os.getenv("E2B_TEMPLATE", DEFAULT_TEMPLATE)
    try:
        if os.getenv("E2B_TEMPLATE_BACKGROUND") == "1":
            info = Template.build_in_background(template, name=name)
            print(
                json.dumps(
                    {
                        "template_id": info.template_id,
                        "build_id": info.build_id,
                        "name": name,
                        "status": "submitted",
                    }
                )
            )
            return
        Template.build(template, name=name)
    except Exception as exc:
        raise SystemExit(str(concise_e2b_error(exc))) from exc


if __name__ == "__main__":
    build()
