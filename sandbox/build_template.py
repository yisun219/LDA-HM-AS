#!/usr/bin/env python3
"""Build the shared E2B lda-base template without persisting credentials."""
from __future__ import annotations

import os
import base64
from pathlib import Path

from e2b import Sandbox, Template
from e2b.connection_config import ConnectionConfig
from e2b.template_sync import build_api


TEMPLATE_NAME = os.getenv("E2B_TEMPLATE", "lda-base")
ROOT = Path(__file__).resolve().parent / "lda-base"


def configure_shared_gateway() -> None:
    api_url = os.getenv("E2B_API_URL", "")
    sandbox_url = os.getenv("E2B_SANDBOX_URL", api_url)
    if api_url != sandbox_url:
        return
    original_getter = ConnectionConfig.sandbox_headers.fget
    if original_getter is None:
        return

    def sandbox_headers(config: ConnectionConfig) -> dict[str, str]:
        headers = dict(original_getter(config))
        headers["X-API-KEY"] = config.api_key
        return headers

    ConnectionConfig.sandbox_headers = property(sandbox_headers)

    # E2B SDK 2.10.2 still sends deprecated `alias`; the shared gateway has
    # already moved to required `names`. Keep this compatibility local to the
    # template builder.
    request_type = build_api.TemplateBuildRequestV3
    if not getattr(request_type, "_lda_names_compat", False):
        def compatible_request(*, alias, cpu_count, memory_mb):
            request = request_type(cpu_count=cpu_count, memory_mb=memory_mb)
            request.additional_properties["name"] = alias
            return request

        compatible_request._lda_names_compat = True
        build_api.TemplateBuildRequestV3 = compatible_request


def build() -> None:
    configure_shared_gateway()
    if Template.alias_exists(TEMPLATE_NAME) and os.getenv("E2B_REBUILD", "0") != "1":
        print(f"template already exists: {TEMPLATE_NAME}")
        return

    template = (
        Template()
        .from_ubuntu_image("26.04")
        .run_cmd(
            "apt-get update && apt-get install -y --no-install-recommends "
            "build-essential clang cmake ninja-build meson pkg-config git git-lfs "
            "python3 python3-pip python3-venv nodejs npm binutils elfutils abigail-tools "
            "libffi-dev strace linux-tools-generic devscripts debhelper ca-certificates "
            "jq curl wget procps file time && rm -rf /var/lib/apt/lists/*"
        )
        .run_cmd(
            "npm install -g @anthropic-ai/claude-code "
            "@earendil-works/pi-coding-agent playwright && "
            "npx playwright install --with-deps chromium"
        )
        .run_cmd("mkdir -p /opt/lda/{bin,skills,harness/checks,work,evidence}")
    )
    mappings = (
        (ROOT / "skills", Path("/opt/lda/skills")),
        (ROOT / "harness", Path("/opt/lda/harness")),
        (ROOT / "checks", Path("/opt/lda/harness/checks")),
    )
    for source, destination in mappings:
        for local in sorted(source.rglob("*")):
            if not local.is_file():
                continue
            remote = destination / local.relative_to(source)
            encoded = base64.b64encode(local.read_bytes()).decode("ascii")
            template = template.run_cmd(
                f"mkdir -p {remote.parent} && printf %s {encoded} | base64 -d > {remote}"
            )
    template = (
        template
        .run_cmd("chmod +x /opt/lda/harness/*.sh /opt/lda/harness/checks/*.sh")
        .run_cmd(
            "git clone https://github.com/intel/intel-performance-skills.git "
            "/opt/lda/skills/intel-performance-skills && "
            "git -C /opt/lda/skills/intel-performance-skills checkout "
            "e9d0b6410fb1ad7a50fb81e0868fd23ae886882c && "
            "rm -rf /opt/lda/skills/intel-performance-skills/.git"
        )
        .set_workdir("/opt/lda/work")
    )
    Template.build(
        template,
        TEMPLATE_NAME,
        skip_cache=os.getenv("E2B_REBUILD", "0") == "1",
    )
    print(f"built template: {TEMPLATE_NAME}")


def smoke() -> None:
    configure_shared_gateway()
    with Sandbox.create(template=TEMPLATE_NAME, timeout=120) as sandbox:
        mappings = (
            (ROOT / "harness", "/opt/lda/harness"),
            (ROOT / "checks", "/opt/lda/harness/checks"),
            (ROOT / "skills", "/opt/lda/skills"),
        )
        for source, destination in mappings:
            for local in sorted(source.rglob("*")):
                if local.is_file():
                    remote = destination + "/" + str(local.relative_to(source)).replace("\\", "/")
                    sandbox.files.write(remote, local.read_bytes())
        result = sandbox.commands.run(
            "chmod +x /opt/lda/harness/lda-agent-harness.sh /opt/lda/harness/checks/*.sh && "
            "test -x /opt/lda/harness/lda-agent-harness.sh && "
            "test -f /opt/lda/skills/lda-abi-ffi-fence.md && "
            "python3 --version && uname -m"
        )
        print(result.stdout, end="")
        if result.exit_code != 0:
            raise RuntimeError(result.stderr)


if __name__ == "__main__":
    build()
    if os.getenv("E2B_SMOKE", "1") == "1":
        smoke()
