from __future__ import annotations

import asyncio
import shlex
import time
from dataclasses import dataclass
from typing import Any
from uuid import uuid4


@dataclass(frozen=True)
class DurableCommandResult:
    command_id: str
    pid: int
    exit_code: int
    stdout: str
    stderr: str


async def run_durable_command(
    sandbox: Any,
    command: str,
    *,
    timeout: int,
    envs: dict[str, str] | None = None,
    command_id: str | None = None,
    reconnect_interval: float = 1.0,
) -> DurableCommandResult:
    """Run a command with output and status persisted inside the Sandbox."""

    identifier = command_id or uuid4().hex
    root = f"/opt/lda/command-state/{identifier}"
    stdout_path = f"{root}/stdout"
    stderr_path = f"{root}/stderr"
    status_path = f"{root}/status"
    pid_path = f"{root}/pid"
    wrapper = (
        f"mkdir -p {shlex.quote(root)}; "
        f"rm -f {shlex.quote(status_path)}; "
        "set +e; "
        f"( {command} ) >{shlex.quote(stdout_path)} 2>{shlex.quote(stderr_path)}; "
        "lda_status=$?; "
        f"printf '%s\\n' \"$lda_status\" >{shlex.quote(status_path)}; "
        "exit \"$lda_status\""
    )
    launch_command = (
        f"nohup setsid sh -lc {shlex.quote(wrapper)} "
        ">/dev/null 2>&1 </dev/null & printf '%s\\n' $!"
    )
    launch = await sandbox.commands.run(
        f"sh -lc {shlex.quote(launch_command)}",
        timeout=30,
        envs=envs or {},
    )
    if launch.exit_code != 0 or not str(launch.stdout).strip().isdigit():
        raise RuntimeError(f"could not launch durable command: {launch.stderr}")
    pid = int(str(launch.stdout).strip())
    await sandbox.files.write(pid_path, f"{pid}\n")

    deadline = time.monotonic() + timeout
    current = sandbox
    last_error: Exception | None = None
    while time.monotonic() < deadline:
        try:
            status_text = _as_text(await current.files.read(status_path)).strip()
            if status_text:
                return DurableCommandResult(
                    command_id=identifier,
                    pid=pid,
                    exit_code=int(status_text),
                    stdout=_as_text(await current.files.read(stdout_path)),
                    stderr=_as_text(await current.files.read(stderr_path)),
                )
        except Exception as error:
            last_error = error

        await asyncio.sleep(min(reconnect_interval, max(0.0, deadline - time.monotonic())))
        try:
            current = await _reconnect(current)
        except Exception as error:
            last_error = error

    detail = f": {type(last_error).__name__}: {last_error}" if last_error else ""
    raise TimeoutError(f"durable command did not publish status after {timeout}s{detail}")


async def _reconnect(sandbox: Any) -> Any:
    connector = getattr(type(sandbox), "connect", None)
    if connector is None:
        connector = getattr(sandbox, "connect", None)
    if connector is None:
        return sandbox
    return await connector(sandbox_id=str(sandbox.sandbox_id))


def _as_text(value: Any) -> str:
    return value.decode() if isinstance(value, bytes) else str(value)
