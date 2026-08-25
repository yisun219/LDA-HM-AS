from __future__ import annotations

import json
import os
import secrets
import base64
import shlex
import asyncio
from hashlib import sha256
from pathlib import Path
from typing import Any

from e2b import AsyncSandbox, AsyncVolume
from e2b.sandbox.sandbox_api import SandboxQuery

from lda.config import LDAConfig
from lda.controller import RunRequest
from lda.artifacts import ArtifactStore

from .shared_gateway import configure_shared_gateway
from .pagination import iterate_pages


async def get_volume(run_id: str, *, create: bool) -> AsyncVolume:
    name = f"lda-run-{run_id}"
    for info in await AsyncVolume.list():
        if info.name == name:
            return await AsyncVolume.connect(info.volume_id)
    if not create:
        raise KeyError(f"no E2B volume for run {run_id}")
    return await AsyncVolume.create(name)


async def launch_controller(
    request: RunRequest,
    config: LDAConfig,
    *,
    codex_auth: Path,
) -> dict[str, Any]:
    config.e2b.apply_public_environment()
    api_key = config.e2b.api_key()
    configure_shared_gateway()
    provider = {
        "base_url": os.getenv("LDA_CODEX_BASE_URL", "").rstrip("/"),
        "api_key": os.getenv("LDA_CODEX_API_KEY", ""),
        "wire_api": os.getenv("LDA_CODEX_WIRE_API", "responses"),
    }
    use_provider = bool(provider["base_url"] and provider["api_key"])
    if not use_provider:
        if not codex_auth.is_file() or codex_auth.stat().st_size <= 2:
            raise RuntimeError("Codex provider credential or authentication file is unavailable")
        if codex_auth.stat().st_mode & 0o077:
            raise RuntimeError("Codex authentication file must be private (0600)")
    try:
        volume = await get_volume(request.run_id, create=True)
    except Exception as error:
        if not _is_volume_unavailable(error):
            raise
        volume = None
    local_artifacts = ArtifactStore(config.artifact_root)
    source_files: list[tuple[str, bytes, str]] = []
    for index, source in enumerate(request.research_snapshot.source_artifacts):
        content = local_artifacts.read_bytes(source.artifact_ref)
        if sha256(content).hexdigest() != source.sha256:
            raise RuntimeError(f"research source changed after ingest: {source.file_name}")
        campaign_name = f"campaign-inputs/{index + 1:02d}-{Path(source.file_name).name}"
        source_files.extend([
            (f"artifacts/objects/{source.artifact_ref[:2]}/{source.artifact_ref[2:]}", content, "0444"),
            (campaign_name, content, "0444"),
            (f"{campaign_name}.sha256", f"{source.sha256}  {Path(source.file_name).name}\n".encode(), "0444"),
        ])
    if volume is not None:
        await volume.write_file("request.json", request.model_dump_json(indent=2), mode=0o444, force=True)
        for path, content, mode in source_files:
            await volume.write_file(path, content, mode=int(mode, 8), force=True)
    signing_key = secrets.token_urlsafe(48)
    metadata = {
        "project": "lda",
        "run_id": request.run_id,
        "mission_id": "",
        "candidate_id": "",
        "role": "controller",
        "lease_id": f"controller-{request.run_id}",
        "owner": "lda-controller",
    }
    create_kwargs = {
        "timeout": 86_400,
        "metadata": metadata,
        "envs": {
            "E2B_API_URL": config.e2b.api_url,
            "E2B_SANDBOX_URL": config.e2b.sandbox_url,
            "E2B_API_KEY": api_key,
            "E2B_ACCESS_TOKEN": config.e2b.access_token,
            config.capability_signing_key_env: signing_key,
        },
        **({"volume_mounts": {"/opt/lda/persist": volume}} if volume is not None else {}),
    }
    controller = await _create_controller_with_retry(config.e2b.controller_template, **create_kwargs)
    controller_id = str(controller.sandbox_id)
    await controller.commands.run("mkdir -p /opt/lda/secrets /opt/lda/persist/logs")
    if volume is None:
        await controller.files.write("/opt/lda/persist/request.json", request.model_dump_json(indent=2))
        for path, content, _mode in source_files:
            await controller.commands.run(f"mkdir -p /opt/lda/persist/{shlex.quote(str(Path(path).parent))}")
            await controller.files.write(f"/opt/lda/persist/{path}", content)
    secret_path = "/opt/lda/secrets/codex-provider.json" if use_provider else "/opt/lda/secrets/codex-auth.json"
    secret_content = json.dumps(provider).encode() if use_provider else codex_auth.read_bytes()
    await controller.files.write(secret_path, secret_content)
    protected = await controller.commands.run(f"chmod 0600 {secret_path}")
    if protected.exit_code != 0:
        await controller.kill()
        raise RuntimeError("could not protect controller Codex credential")
    command = (
        "cd /opt/lda/runtime && "
        f"LDA_CONTROLLER_SANDBOX_ID={controller_id} "
        "lda controller execute --request /opt/lda/persist/request.json "
        "--persist-root /opt/lda/persist "
        ">>/opt/lda/persist/logs/controller.stdout "
        "2>>/opt/lda/persist/logs/controller.stderr"
    )
    process = await controller.commands.run(command, background=True)
    controller_record = json.dumps({"sandbox_id": controller_id, "pid": int(process.pid)}, sort_keys=True)
    if volume is not None:
        await volume.write_file("controller.json", controller_record, mode=0o444, force=True)
    else:
        await controller.files.write("/opt/lda/persist/controller.json", controller_record)
    return {"run_id": request.run_id, "controller_sandbox_id": controller_id, "pid": int(process.pid), "volume_id": volume.volume_id if volume is not None else None, "persistence": "e2b-volume" if volume is not None else "e2b-controller-filesystem"}


async def read_run_file(run_id: str, relative: str) -> str:
    try:
        volume = await get_volume(run_id, create=False)
        value = await volume.read_file(relative, format="text")
        return str(value)
    except Exception as error:
        if not _is_volume_unavailable(error) and not isinstance(error, KeyError):
            raise
        controller = await _find_controller(run_id)
        encoded = await controller.commands.run(f"base64 -w0 /opt/lda/persist/{shlex.quote(relative)}")
        if encoded.exit_code != 0:
            raise FileNotFoundError(relative)
        return base64.b64decode(encoded.stdout).decode()


async def resume_controller(run_id: str, config: LDAConfig, *, codex_auth: Path) -> dict[str, Any]:
    request = RunRequest.model_validate_json(await read_run_file(run_id, "request.json"))
    return await launch_controller(request, config, codex_auth=codex_auth)


async def _find_controller(run_id: str) -> AsyncSandbox:
    from e2b.sandbox.sandbox_api import SandboxQuery
    from .pagination import iterate_pages

    paginator = AsyncSandbox.list(query=SandboxQuery(metadata={"project": "lda", "run_id": run_id, "role": "controller"}))
    async for item in iterate_pages(paginator):
        sandbox_id = str(getattr(item, "sandbox_id", getattr(item, "id", "")))
        if sandbox_id:
            return await AsyncSandbox.connect(sandbox_id=sandbox_id)
    raise KeyError(f"no E2B controller for run {run_id}")


def _is_volume_unavailable(error: Exception) -> bool:
    message = str(error).lower()
    return "route not found" in message or "404" in message and "volume" in message


async def _create_controller_with_retry(template: str, **kwargs: Any) -> Any:
    """Wait for a freshly built template and avoid duplicate controller leases."""
    metadata = kwargs.get("metadata", {})
    for attempt in range(12):
        paginator = AsyncSandbox.list(query=SandboxQuery(metadata=metadata))
        async for item in iterate_pages(paginator):
            sandbox_id = str(getattr(item, "sandbox_id", getattr(item, "id", "")))
            if sandbox_id:
                return await AsyncSandbox.connect(sandbox_id=sandbox_id, timeout=kwargs.get("timeout", 86_400))
        try:
            return await AsyncSandbox.create(template=template, **kwargs)
        except Exception as error:
            if "not ready" not in str(error).lower() or attempt == 11:
                raise
            await asyncio.sleep(min(2 ** attempt, 30))
    raise RuntimeError(f"controller template was not ready: {template}")
