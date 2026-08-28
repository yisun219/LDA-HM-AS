"""Unix-socket broker: the flow process lends its live sandbox connection.

The shared E2B gateway only serves sandbox routes to the client that created
the sandbox; a second process attaching by id gets `route not found` on both
the file and the process APIs. The relay processes hmz spawns for agent
turns therefore do not attach: the flow process (which holds the one working
client) serves a tiny newline-JSON protocol over a user-only unix socket,
and relays marshal their `run`/`put` through it. One connection per request;
concurrent requests are safe (the SDK client multiplexes) so a watchdog poll
is never starved by a long agent turn.
"""
from __future__ import annotations

import base64
import json
import os
import socket
import socketserver
import threading
from pathlib import Path
from typing import Optional

from .sandbox import Sandbox, SandboxResult

_MAX_REQUEST = 64 * 1024 * 1024


class SandboxBroker:
    def __init__(self, sandbox: Sandbox, socket_path: Path) -> None:
        self.sandbox = sandbox
        self.socket_path = Path(socket_path)
        self._server: Optional[socketserver.ThreadingUnixStreamServer] = None
        self._thread: Optional[threading.Thread] = None

    def start(self) -> Path:
        self.socket_path.parent.mkdir(parents=True, exist_ok=True)
        self.socket_path.unlink(missing_ok=True)
        broker = self

        class Handler(socketserver.StreamRequestHandler):
            def handle(self) -> None:
                try:
                    line = self.rfile.readline(_MAX_REQUEST)
                    request = json.loads(line)
                except Exception:
                    return
                response = broker._serve(request)
                try:
                    self.wfile.write(json.dumps(response).encode() + b"\n")
                except Exception:
                    pass

        server = socketserver.ThreadingUnixStreamServer(str(self.socket_path), Handler)
        server.daemon_threads = True
        os.chmod(self.socket_path, 0o600)
        self._server = server
        self._thread = threading.Thread(target=server.serve_forever, daemon=True)
        self._thread.start()
        return self.socket_path

    def _serve(self, request: dict) -> dict:
        try:
            operation = request.get("op")
            if operation == "ping":
                return {"ok": True, "sandbox_id": self.sandbox.sandbox_id}
            if operation == "run":
                result = self.sandbox.run(
                    tuple(request["command"]),
                    timeout_seconds=int(request.get("timeout", 900)),
                )
                return {
                    "ok": True,
                    "exit": result.exit_code,
                    "stdout_b64": base64.b64encode(result.stdout.encode()).decode(),
                    "stderr_b64": base64.b64encode(result.stderr.encode()).decode(),
                    "duration": result.duration_seconds,
                    "sandbox_id": result.sandbox_id,
                }
            if operation == "put":
                content = base64.b64decode(request["content_b64"])
                import tempfile

                staging = Path(tempfile.mkstemp(prefix="lda-broker-put-")[1])
                try:
                    staging.write_bytes(content)
                    self.sandbox.put(staging, str(request["path"]))
                finally:
                    staging.unlink(missing_ok=True)
                return {"ok": True}
            return {"ok": False, "error": f"unknown op {operation!r}"}
        except Exception as error:
            return {"ok": False, "error": str(error)[-1500:]}

    def close(self) -> None:
        if self._server is not None:
            self._server.shutdown()
            self._server.server_close()
        self.socket_path.unlink(missing_ok=True)


class BrokerClient:
    """Duck-typed sandbox front (run/put) over the broker socket."""

    def __init__(self, socket_path: Path) -> None:
        self.socket_path = Path(socket_path)
        self.sandbox_id = self._request({"op": "ping"}).get("sandbox_id", "broker")

    def _request(self, request: dict, timeout: float = 7200.0) -> dict:
        connection = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        connection.settimeout(timeout)
        try:
            connection.connect(str(self.socket_path))
            connection.sendall(json.dumps(request).encode() + b"\n")
            chunks = []
            while True:
                block = connection.recv(1 << 20)
                if not block:
                    break
                chunks.append(block)
                if block.endswith(b"\n"):
                    break
            value = json.loads(b"".join(chunks))
        finally:
            connection.close()
        if not value.get("ok"):
            raise RuntimeError(f"broker refused: {value.get('error', 'unknown')}")
        return value

    def run(self, command, *, timeout_seconds: int = 900, envs=None) -> SandboxResult:
        if envs:
            command = ("env",) + tuple(
                f"{key}={value}" for key, value in sorted(envs.items())
            ) + tuple(command)
        value = self._request(
            {"op": "run", "command": list(command), "timeout": timeout_seconds},
            timeout=timeout_seconds + 300,
        )
        return SandboxResult(
            tuple(command),
            int(value["exit"]),
            base64.b64decode(value["stdout_b64"]).decode("utf-8", "replace"),
            base64.b64decode(value["stderr_b64"]).decode("utf-8", "replace"),
            float(value.get("duration", 0.0)),
            str(value.get("sandbox_id", "broker")),
        )

    def put(self, local: Path, remote: str) -> None:
        content = Path(local).read_bytes()
        self._request(
            {
                "op": "put",
                "path": remote,
                "content_b64": base64.b64encode(content).decode(),
            },
            timeout=600,
        )
