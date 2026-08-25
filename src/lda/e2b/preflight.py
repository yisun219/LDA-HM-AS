from __future__ import annotations

import importlib.metadata
import json
import asyncio
from dataclasses import dataclass, field
from uuid import uuid4

from e2b import AsyncSandbox, Template
from e2b.sandbox.sandbox_api import SandboxQuery

from lda.config import E2BConfig

from .shared_gateway import configure_shared_gateway
from .pagination import iterate_pages


@dataclass
class PreflightReport:
    preflight_id: str
    template: str
    sandbox_ids: list[str] = field(default_factory=list)
    background_pid: int | None = None
    snapshot_id: str | None = None
    fork_supported: bool = False
    checks: dict[str, str] = field(default_factory=dict)

    def to_json(self) -> str:
        return json.dumps(self.__dict__, indent=2, sort_keys=True)


async def run_preflight(
    config: E2BConfig,
    *,
    template: str | None = None,
    sandbox_class=AsyncSandbox,
    template_class=Template,
) -> PreflightReport:
    config.apply_public_environment()
    config.api_key()
    configure_shared_gateway()
    installed = importlib.metadata.version("e2b")
    if installed != config.sdk_version:
        raise RuntimeError(f"E2B SDK mismatch: installed={installed} required={config.sdk_version}")
    target = template or config.base_template
    if not template_class.exists(target):
        raise RuntimeError(f"E2B template does not exist: {target}")
    report = PreflightReport(preflight_id=uuid4().hex, template=target)
    metadata = {
        "project": "lda",
        "run_id": report.preflight_id,
        "mission_id": "",
        "candidate_id": "",
        "role": "preflight",
        "lease_id": report.preflight_id,
        "owner": "lda-controller",
        "preflight_id": report.preflight_id,
    }
    live: dict[str, object] = {}
    try:
        sandbox = await sandbox_class.create(template=target, timeout=180, metadata=metadata, envs={})
        live[str(sandbox.sandbox_id)] = sandbox
        report.sandbox_ids.append(str(sandbox.sandbox_id))
        for name, command in {
            "uname": "uname -a",
            "os_release": "cat /etc/os-release",
            "lscpu": "lscpu",
        }.items():
            result = await sandbox.commands.run(command, timeout=60)
            if result.exit_code != 0:
                raise RuntimeError(f"preflight {name} failed: {result.stderr}")
            report.checks[name] = result.stdout
        written = await sandbox.commands.run(
            "mkdir -p /tmp/lda-preflight && printf persistent >/tmp/lda-preflight/value && cat /tmp/lda-preflight/value"
        )
        if written.exit_code != 0 or written.stdout != "persistent":
            raise RuntimeError("preflight file write/read failed")
        foreground = await sandbox.commands.run("printf foreground")
        if foreground.exit_code != 0 or foreground.stdout != "foreground":
            raise RuntimeError("preflight foreground command failed")
        background = await sandbox.commands.run(
            "sh -c 'echo bg-out >>/tmp/lda-preflight/stdout; echo bg-err >>/tmp/lda-preflight/stderr; sleep 2'",
            background=True,
        )
        report.background_pid = int(background.pid)
        reconnected = await sandbox_class.connect(sandbox_id=str(sandbox.sandbox_id), timeout=180)
        handle = await reconnected.commands.connect(report.background_pid)
        await handle.wait()
        persisted = await reconnected.commands.run(
            "test \"$(cat /tmp/lda-preflight/stdout)\" = bg-out && test \"$(cat /tmp/lda-preflight/stderr)\" = bg-err"
        )
        if persisted.exit_code != 0:
            raise RuntimeError("preflight background stdout/stderr persistence failed")
        snapshot = await reconnected.create_snapshot(name=f"lda-preflight-{report.preflight_id}")
        report.snapshot_id = str(snapshot.snapshot_id)
        from_snapshot = None
        snapshot_error: Exception | None = None
        for attempt in range(8):
            try:
                from_snapshot = await sandbox_class.create(
                    template=report.snapshot_id,
                    timeout=120,
                    metadata={**metadata, "lease_id": uuid4().hex, "role": "snapshot-check"},
                    envs={},
                )
                break
            except Exception as error:
                snapshot_error = error
                if "not ready" not in str(error).lower() or attempt == 7:
                    raise
                await asyncio.sleep(min(2 ** attempt, 20))
        if from_snapshot is None:
            raise RuntimeError(f"snapshot restore failed: {snapshot_error}")
        live[str(from_snapshot.sandbox_id)] = from_snapshot
        report.sandbox_ids.append(str(from_snapshot.sandbox_id))
        snapshot_check = await from_snapshot.commands.run("cat /tmp/lda-preflight/value")
        if snapshot_check.exit_code != 0 or snapshot_check.stdout != "persistent":
            raise RuntimeError("preflight snapshot restore failed")
        try:
            forks = await reconnected.fork(timeout=120, count=1)
            forked = forks[0]
            if isinstance(forked, Exception):
                raise forked
            live[str(forked.sandbox_id)] = forked
            report.sandbox_ids.append(str(forked.sandbox_id))
            fork_check = await forked.commands.run("cat /tmp/lda-preflight/value")
            if fork_check.exit_code != 0 or fork_check.stdout != "persistent":
                raise RuntimeError("preflight fork filesystem check failed")
            report.fork_supported = True
        except Exception as error:
            report.checks["fork"] = f"snapshot fallback: {type(error).__name__}"
        paginator = sandbox_class.list(query=SandboxQuery(metadata={"preflight_id": report.preflight_id}))
        discovered: list[str] = []
        async for item in iterate_pages(paginator):
            discovered.append(str(getattr(item, "sandbox_id", getattr(item, "id", ""))))
        if str(sandbox.sandbox_id) not in discovered:
            raise RuntimeError("preflight metadata lookup failed")
        report.checks["metadata"] = "ok"
        return report
    finally:
        for sandbox in tuple(live.values()):
            try:
                await sandbox.kill()
            except Exception:
                pass
        paginator = sandbox_class.list(query=SandboxQuery(metadata={"preflight_id": report.preflight_id}))
        async for item in iterate_pages(paginator):
            sandbox_id = str(getattr(item, "sandbox_id", getattr(item, "id", "")))
            if sandbox_id:
                try:
                    orphan = await sandbox_class.connect(sandbox_id=sandbox_id)
                    await orphan.kill()
                except Exception:
                    pass
