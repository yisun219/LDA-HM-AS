#!/usr/bin/env python3
"""Build the shared E2B lda-base template without persisting credentials."""
from __future__ import annotations

import os
import base64
import time
from pathlib import Path

from e2b import Sandbox, Template
from e2b.connection_config import ConnectionConfig
from e2b.template_sync import build_api


TEMPLATE_NAME = os.getenv("E2B_TEMPLATE", "lda-base")
BASE_TEMPLATE = os.getenv("E2B_BASE_TEMPLATE", "")
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

    if BASE_TEMPLATE:
        template = (
            Template()
            .from_template(BASE_TEMPLATE)
            .set_user("root")
            .run_cmd(
                "sudo -n mkdir -p /opt/lda/ms-playwright && "
                "sudo -n cp -a /root/.cache/ms-playwright/. /opt/lda/ms-playwright/ && "
                "sudo -n npm install -g @openai/codex@0.149.1 && "
                "sudo -n chown -R user:user /opt/lda /home/user"
            )
            .set_workdir("/opt/lda/work")
            .set_envs({"PLAYWRIGHT_BROWSERS_PATH": "/opt/lda/ms-playwright"})
            .set_user("user")
        )
        build_info = Template.build_in_background(
            template,
            TEMPLATE_NAME,
            skip_cache=os.getenv("E2B_REBUILD", "0") == "1",
        )
        _wait_for_build(build_info)
        print(f"built template: {TEMPLATE_NAME}")
        return

    template = (
        Template()
        .from_ubuntu_image("26.04")
        .set_user("root")
        .run_cmd(
            "apt-get update && apt-get install -y --no-install-recommends "
            "build-essential clang cmake ninja-build meson pkg-config git git-lfs "
            "python3 python3-pip python3-venv nodejs npm binutils elfutils abigail-tools "
            "libffi-dev strace linux-tools-generic devscripts debhelper dpkg-dev fakeroot "
            "ca-certificates jq curl wget procps file time sudo xz-utils squashfs-tools "
            "libpng-dev libpng-tools python3-pil libgdk-pixbuf2.0-bin "
            "xvfb xauth dbus-x11 fonts-dejavu-core && rm -rf /var/lib/apt/lists/*"
        )
        .run_cmd(
            "mkdir -p /opt/lda/ms-playwright && "
            "npm install -g @anthropic-ai/claude-code @openai/codex "
            "@earendil-works/pi-coding-agent playwright && "
            "PLAYWRIGHT_BROWSERS_PATH=/opt/lda/ms-playwright "
            "npx playwright install --with-deps chromium"
        )
        .run_cmd(
            "id -u user >/dev/null 2>&1 || useradd --create-home --shell /bin/bash user; "
            "printf '%s\\n' 'user ALL=(ALL) NOPASSWD:ALL' >/etc/sudoers.d/lda-user; "
            "chmod 0440 /etc/sudoers.d/lda-user; "
            "mkdir -p /opt/lda/{bin,skills,harness/checks,baseline,work,evidence}; "
            "chown -R user:user /opt/lda"
        )
    )
    mappings = (
        (ROOT / "skills", Path("/opt/lda/skills")),
        (ROOT / "harness", Path("/opt/lda/harness")),
        (ROOT / "checks", Path("/opt/lda/harness/checks")),
        (ROOT / "baseline", Path("/opt/lda/baseline")),
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
        .run_cmd("find /opt/lda/harness -type f -name '*.sh' -exec chmod +x {} +")
        .run_cmd("chown -R user:user /opt/lda /home/user")
        .set_workdir("/opt/lda/work")
        .set_envs({"PLAYWRIGHT_BROWSERS_PATH": "/opt/lda/ms-playwright"})
        .set_user("user")
    )
    build_info = Template.build_in_background(
        template,
        TEMPLATE_NAME,
        skip_cache=os.getenv("E2B_REBUILD", "0") == "1",
    )
    _wait_for_build(build_info)
    print(f"built template: {TEMPLATE_NAME}")


def _wait_for_build(build_info) -> None:
    print(
        f"build requested: template={build_info.template_id} "
        f"build={build_info.build_id}",
        flush=True,
    )
    logs_offset = 0
    while True:
        current = Template.get_build_status(build_info, logs_offset=logs_offset)
        entries = tuple(getattr(current, "log_entries", ()))
        logs_offset += len(entries)
        for entry in entries:
            print(getattr(entry, "message", str(entry)), flush=True)
        status = getattr(getattr(current, "status", ""), "value", current.status)
        if status == "ready":
            break
        if status == "error":
            reason = getattr(current, "reason", "unknown template build failure")
            raise RuntimeError(f"template build failed: {reason}")
        time.sleep(2)


def smoke() -> None:
    configure_shared_gateway()
    with Sandbox.create(template=TEMPLATE_NAME, timeout=120) as sandbox:
        mappings = (
            (ROOT / "harness", "/opt/lda/harness"),
            (ROOT / "checks", "/opt/lda/harness/checks"),
            (ROOT / "skills", "/opt/lda/skills"),
            (ROOT / "baseline", "/opt/lda/baseline"),
        )
        for source, destination in mappings:
            for local in sorted(source.rglob("*")):
                if local.is_file():
                    remote = destination + "/" + str(local.relative_to(source)).replace("\\", "/")
                    sandbox.files.write(remote, local.read_bytes())
        result = sandbox.commands.run(
            "find /opt/lda/harness -type f -name '*.sh' -exec chmod +x {} + && "
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
