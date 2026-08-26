from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass
from enum import StrEnum
from hashlib import sha256
from typing import Any
from uuid import uuid4

from e2b import AsyncSandbox
from e2b.sandbox.sandbox_api import SandboxQuery

from lda.config import E2BConfig
from lda.security import child_environment
from lda.state import EventStore

from .shared_gateway import configure_shared_gateway
from .pagination import iterate_pages


class SandboxRole(StrEnum):
    CONTROLLER = "controller"
    AGENT = "agent-runtime"
    WORKSPACE = "workspace"
    JUDGE = "judge"
    E2E = "e2e"
    PREFLIGHT = "preflight"


@dataclass(frozen=True)
class SandboxLease:
    lease_id: str
    run_id: str
    mission_id: str
    candidate_id: str
    role: SandboxRole
    template: str

    def metadata(self) -> dict[str, str]:
        return {
            "project": "lda",
            "run_id": self.run_id,
            "mission_id": self.mission_id,
            "candidate_id": self.candidate_id,
            "role": self.role.value,
            "lease_id": self.lease_id,
            "owner": "lda-controller",
        }

    @classmethod
    def create(
        cls,
        *,
        run_id: str,
        role: SandboxRole,
        template: str,
        mission_id: str = "",
        candidate_id: str = "",
    ) -> "SandboxLease":
        return cls(uuid4().hex, run_id, mission_id, candidate_id, role, template)

    @classmethod
    def deterministic(
        cls,
        key: str,
        *,
        run_id: str,
        role: SandboxRole,
        template: str,
        mission_id: str = "",
        candidate_id: str = "",
    ) -> "SandboxLease":
        lease_id = sha256(f"lda:{run_id}:{key}".encode()).hexdigest()
        return cls(lease_id, run_id, mission_id, candidate_id, role, template)


class E2BSandboxManager:
    def __init__(
        self,
        config: E2BConfig,
        store: EventStore,
        *,
        max_live: int,
        sandbox_class: type[Any] = AsyncSandbox,
    ) -> None:
        config.apply_public_environment()
        config.api_key()
        configure_shared_gateway()
        self.config = config
        self.store = store
        self._sandbox_class = sandbox_class
        self._semaphore = asyncio.Semaphore(max_live)
        self._owned: dict[str, Any] = {}
        self._acquired: set[str] = set()

    async def find_by_lease(self, lease_id: str) -> Any | None:
        paginator = self._sandbox_class.list(query=SandboxQuery(metadata={"lease_id": lease_id}))
        async for item in iterate_pages(paginator):
            sandbox_id = str(getattr(item, "sandbox_id", getattr(item, "id", "")))
            if sandbox_id:
                return await self._sandbox_class.connect(sandbox_id=sandbox_id)
        return None

    async def create(
        self,
        lease: SandboxLease,
        *,
        timeout: int = 3600,
        agent_runtime: bool = False,
        envs: dict[str, str] | None = None,
        allow_internet_access: bool = True,
    ) -> Any:
        existing_record = self.store.lease(lease.lease_id)
        if existing_record and existing_record.get("sandbox_id"):
            await self._acquire(lease.lease_id)
            try:
                sandbox = await self._sandbox_class.connect(
                    sandbox_id=existing_record["sandbox_id"], timeout=timeout
                )
                self._owned[lease.lease_id] = sandbox
                return sandbox
            except Exception:
                snapshot_id = existing_record.get("metadata", {}).get("snapshot_id")
                if snapshot_id:
                    try:
                        sandbox = await _create_snapshot_with_retry(
                            self._sandbox_class,
                            snapshot_id,
                            timeout=timeout,
                            metadata=lease.metadata(),
                            envs=child_environment(envs or {}, agent_runtime=agent_runtime),
                            allow_internet_access=allow_internet_access,
                        )
                    except Exception:
                        self._release(lease.lease_id)
                        raise
                    sandbox_id = str(sandbox.sandbox_id)
                    self.store.record_lease(
                        lease.lease_id, lease.run_id, lease.metadata(), "running", sandbox_id
                    )
                    self._owned[lease.lease_id] = sandbox
                    return sandbox
                self._release(lease.lease_id)
                self.store.record_lease(
                    lease.lease_id,
                    lease.run_id,
                    existing_record["metadata"],
                    "stale",
                    existing_record["sandbox_id"],
                )
        existing = await self.find_by_lease(lease.lease_id)
        if existing is not None:
            await self._acquire(lease.lease_id)
            sandbox_id = str(existing.sandbox_id)
            self.store.record_lease(
                lease.lease_id, lease.run_id, lease.metadata(), "running", sandbox_id
            )
            self._owned[lease.lease_id] = existing
            return existing
        self.store.record_lease(lease.lease_id, lease.run_id, lease.metadata(), "creating")
        filtered = child_environment(envs or {}, agent_runtime=agent_runtime)
        await self._acquire(lease.lease_id)
        try:
            sandbox = await _create_template_with_retry(
                self._sandbox_class,
                lease.template,
                timeout=timeout,
                metadata=lease.metadata(),
                envs=filtered,
                allow_internet_access=allow_internet_access,
            )
        except Exception:
            recovered = await self.find_by_lease(lease.lease_id)
            if recovered is None:
                self._release(lease.lease_id)
                self.store.record_lease(lease.lease_id, lease.run_id, lease.metadata(), "failed")
                raise
            sandbox = recovered
        sandbox_id = str(sandbox.sandbox_id)
        self.store.record_lease(lease.lease_id, lease.run_id, lease.metadata(), "running", sandbox_id)
        self._owned[lease.lease_id] = sandbox
        return sandbox

    async def pause(self, lease_id: str) -> None:
        sandbox = self._owned.get(lease_id)
        if sandbox is None:
            return
        await sandbox.pause()
        record = self.store.lease(lease_id)
        if record:
            self.store.record_lease(lease_id, record["run_id"], record["metadata"], "paused", record["sandbox_id"])
        self._release(lease_id)

    async def create_snapshot(self, lease_id: str, *, name: str | None = None) -> str:
        sandbox = self._owned.get(lease_id)
        record = self.store.lease(lease_id)
        if sandbox is None:
            if not record or not record.get("sandbox_id"):
                raise KeyError(f"unknown Sandbox lease: {lease_id}")
            sandbox = await self._sandbox_class.connect(sandbox_id=record["sandbox_id"])
        snapshot = await sandbox.create_snapshot(name=name)
        snapshot_id = str(snapshot.snapshot_id)
        self._owned.pop(lease_id, None)
        if record:
            metadata = {**record["metadata"], "snapshot_id": snapshot_id}
            self.store.record_lease(
                lease_id, record["run_id"], metadata, "snapshotted", record["sandbox_id"]
            )
        self._release(lease_id)
        return snapshot_id

    async def kill(self, lease_id: str) -> None:
        sandbox = self._owned.pop(lease_id, None)
        record = self.store.lease(lease_id)
        if sandbox is None and record and record.get("sandbox_id"):
            try:
                sandbox = await self._sandbox_class.connect(sandbox_id=record["sandbox_id"])
            except Exception:
                sandbox = None
        if sandbox is not None:
            try:
                await sandbox.kill()
            except Exception as error:
                if not _is_missing_sandbox(error):
                    raise
            finally:
                self._release(lease_id)
        else:
            self._release(lease_id)
        if record:
            self.store.record_lease(lease_id, record["run_id"], record["metadata"], "killed", record["sandbox_id"])

    async def reap(self, run_id: str) -> list[str]:
        killed: list[str] = []
        paginator = self._sandbox_class.list(
            query=SandboxQuery(metadata={"project": "lda", "run_id": run_id, "owner": "lda-controller"})
        )
        async for item in iterate_pages(paginator):
            sandbox_id = str(getattr(item, "sandbox_id", getattr(item, "id", "")))
            if not sandbox_id:
                continue
            try:
                sandbox = await self._sandbox_class.connect(sandbox_id=sandbox_id)
                await sandbox.kill()
            except Exception as error:
                if not _is_missing_sandbox(error):
                    raise
            killed.append(sandbox_id)
        return killed

    async def close(self) -> None:
        await asyncio.gather(*(self.kill(lease_id) for lease_id in tuple(self._owned)), return_exceptions=True)

    def _release(self, lease_id: str) -> None:
        if lease_id in self._acquired:
            self._acquired.remove(lease_id)
            self._semaphore.release()

    async def _acquire(self, lease_id: str) -> None:
        if lease_id in self._acquired:
            return
        await self._semaphore.acquire()
        self._acquired.add(lease_id)


def _is_missing_sandbox(error: Exception) -> bool:
    # The shared Fact-Lab gateway can return an empty 404 after a successful
    # kill. e2b 2.45.0 attempts to decode that empty body and surfaces the
    # response as JSONDecodeError. Treat it as an idempotent delete only in
    # missing/cleanup paths; normal create and command failures still surface.
    if isinstance(error, json.JSONDecodeError):
        return error.pos == 0 and error.doc == ""
    message = str(error).lower()
    return "404" in message or "not found" in message or "does not exist" in message


async def _create_snapshot_with_retry(sandbox_class: type[Any], snapshot_id: str, **kwargs: Any) -> Any:
    for attempt in range(8):
        try:
            return await sandbox_class.create(template=snapshot_id, **kwargs)
        except Exception as error:
            if "not ready" not in str(error).lower() or attempt == 7:
                raise
            await asyncio.sleep(min(2 ** attempt, 20))
    raise RuntimeError(f"snapshot was not ready: {snapshot_id}")


async def _create_template_with_retry(sandbox_class: type[Any], template: str, **kwargs: Any) -> Any:
    for attempt in range(8):
        try:
            return await sandbox_class.create(template=template, **kwargs)
        except Exception as error:
            if "not ready" not in str(error).lower() or attempt == 7:
                raise
            await asyncio.sleep(min(2 ** attempt, 20))
    raise RuntimeError(f"template was not ready: {template}")
