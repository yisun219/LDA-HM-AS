"""Build the pinned E2B lda-base template without embedding credentials."""

from __future__ import annotations

import base64
import hashlib
import json
import os
import subprocess
import tempfile
import time
import urllib.request
from pathlib import Path

from e2b import Template

from lda_flow.gateway import concise_e2b_error, configure_shared_gateway

INTEL_SKILLS_COMMIT = "e9d0b6410fb1ad7a50fb81e0868fd23ae886882c"
INTEL_SKILLS_SHA256 = "9f505d7d708935b9199efbd088c1c2b24df689e25530ba2ab4fe0c2b6f5532aa"
LDA_COMMIT = "0f61b08"
DEFAULT_TEMPLATE = "lda-base-lda-hm-as"
ROOT = Path(__file__).resolve().parents[2]

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


def _build_log(entry: object) -> None:
    print(str(entry), flush=True)


def _intel_skills_archive() -> bytes:
    url = (
        "https://codeload.github.com/intel/intel-performance-skills/tar.gz/"
        + INTEL_SKILLS_COMMIT
    )
    last_error: Exception | None = None
    for attempt in range(1, 4):
        try:
            with urllib.request.urlopen(url, timeout=60) as response:  # noqa: S310
                payload = response.read()
            digest = hashlib.sha256(payload).hexdigest()
            if digest != INTEL_SKILLS_SHA256:
                raise RuntimeError("Intel Performance Skills archive SHA256 mismatch")
            return payload
        except Exception as exc:  # pragma: no cover - exercised by real template builds
            last_error = exc
            if attempt < 3:
                time.sleep(2 * attempt)
    raise RuntimeError("failed to fetch pinned Intel Performance Skills archive") from last_error


def _lda_archive() -> bytes:
    result = subprocess.run(
        ["git", "archive", "--format=tar.gz", LDA_COMMIT],
        cwd=ROOT,
        check=True,
        stdout=subprocess.PIPE,
    )
    return result.stdout


def _write_template_assets(directory: Path) -> tuple[Path, Path]:
    intel = directory / "intel-performance-skills.tar.gz"
    lda = directory / "lda-flow.tar.gz"
    intel.write_bytes(_intel_skills_archive())
    lda.write_bytes(_lda_archive())
    return intel, lda


def _inject_archive(template: Template, payload: bytes, destination: str, name: str) -> Template:
    encoded = base64.b64encode(payload).decode("ascii")
    archive = f"/opt/.lda-template-assets/{name}.tar.gz.b64"
    template = template.run_cmd(
        f"mkdir -p {destination} /opt/.lda-template-assets && : > {archive}"
    )
    for offset in range(0, len(encoded), 32_000):
        template = template.run_cmd(
            f"printf '%s' '{encoded[offset : offset + 32_000]}' >> {archive}"
        )
    strip = " --strip-components=1" if name == "intel-performance-skills" else ""
    return template.run_cmd(
        f"base64 -d {archive} | tar -xz -C {destination}{strip} && rm -f {archive}"
    )


def build() -> None:
    configure_shared_gateway()
    _patch_gateway_step_parser()
    assets = tempfile.TemporaryDirectory(dir=ROOT, prefix=".lda-template-assets-")
    try:
        intel_archive, lda_archive = _write_template_assets(Path(assets.name))
        template = Template().from_image("ubuntu:26.04")
        template = template.apt_install(BASE_PACKAGES)
        template = template.run_cmd(
            "python3 -m venv /opt/lda-venv && "
            "/opt/lda-venv/bin/pip install --no-cache-dir "
            "'pydantic>=2.9,<3' PyYAML 'e2b==2.15.0'"
        )
        template = template.run_cmd("npm install --global @openai/codex")
        template = _inject_archive(
            template,
            intel_archive.read_bytes(),
            "/opt/intel-performance-skills",
            "intel-performance-skills",
        )
        template = template.run_cmd(
            "cd /opt/intel-performance-skills && "
            "test -f skills/linux-perf/SKILL.md && "
            "test -f skills/performance-patterns/SKILL.md && "
            "test -f skills/phoronix-test-suite/SKILL.md && "
            f"printf '%s\\n' '{INTEL_SKILLS_COMMIT}' > .lda-pinned-commit"
        )
        template = _inject_archive(
            template, lda_archive.read_bytes(), "/opt/lda", "lda-flow"
        )
        template = template.run_cmd(
            f"printf '%s\\n' '{LDA_COMMIT}' > /opt/lda/.lda-pinned-commit"
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
            Template.build(template, name=name, on_build_logs=_build_log)
        except Exception as exc:
            raise SystemExit(str(concise_e2b_error(exc))) from exc
    finally:
        assets.cleanup()


if __name__ == "__main__":
    build()
