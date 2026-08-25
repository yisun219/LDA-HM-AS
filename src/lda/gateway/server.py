from __future__ import annotations

import argparse
import json
import os
import shlex
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path, PurePosixPath
from typing import Any

from e2b import Sandbox

from lda.artifacts import ArtifactStore
from lda.e2b.shared_gateway import configure_shared_gateway
from lda.gateway.capabilities import CapabilityAuthority
from lda.security import SecretRedactor


WORKSPACE_ROOT = PurePosixPath("/opt/lda/work")


def _workspace_path(value: str) -> str:
    path = PurePosixPath(value)
    if not path.is_absolute():
        path = WORKSPACE_ROOT / path
    if path != WORKSPACE_ROOT and WORKSPACE_ROOT not in path.parents:
        raise PermissionError("path escapes candidate workspace")
    return str(path)


class ToolGateway:
    def __init__(self, registry: Path, artifacts: ArtifactStore, authority: CapabilityAuthority) -> None:
        self.registry = registry
        self.artifacts = artifacts
        self.authority = authority
        self.redactor = SecretRedactor()

    def _sandbox(self, workspace_id: str | None) -> Sandbox:
        if not workspace_id:
            raise PermissionError("capability has no workspace")
        registry = json.loads(self.registry.read_text(encoding="utf-8"))
        sandbox_id = registry.get(workspace_id)
        if not sandbox_id:
            raise KeyError(f"unknown workspace: {workspace_id}")
        configure_shared_gateway()
        return Sandbox.connect(sandbox_id=sandbox_id)

    def invoke(self, token: str, tool: str, arguments: dict[str, Any]) -> dict[str, Any]:
        capability = self.authority.verify(token)
        if not capability.permits(
            tool,
            run_id=str(arguments.get("run_id", capability.run_id)),
            mission_id=str(arguments.get("mission_id", capability.mission_id)),
            candidate_id=arguments.get("candidate_id", capability.candidate_id),
        ):
            raise PermissionError(f"capability does not permit {tool}")
        if tool == "artifact.read":
            digest = str(arguments["ref"])
            return {"content": self.artifacts.read_bytes(digest).decode(errors="replace")}
        if tool == "artifact.publish":
            content = str(arguments["content"])
            self.redactor.assert_clean(content)
            return {"ref": self.artifacts.put_bytes(content.encode())}
        if tool in {"candidate.diff", "test_result.read", "benchmark_result.read", "trace.read"}:
            digest = str(arguments["ref"])
            return {"content": self.artifacts.read_bytes(digest).decode(errors="replace")}
        sandbox = self._sandbox(capability.workspace_id)
        if tool == "workspace.read":
            path = _workspace_path(str(arguments["path"]))
            content = sandbox.files.read(path)
            return {"content": content.decode() if isinstance(content, bytes) else str(content)}
        if tool == "workspace.write":
            path = _workspace_path(str(arguments["path"]))
            content = str(arguments["content"])
            self.redactor.assert_clean(content)
            sandbox.files.write(path, content)
            return {"written": path}
        if tool == "workspace.apply_patch":
            patch = str(arguments["patch"])
            self.redactor.assert_clean(patch)
            sandbox.files.write("/tmp/lda-agent.patch", patch)
            result = sandbox.commands.run("git -C /opt/lda/work apply /tmp/lda-agent.patch")
            return _command_result(result)
        if tool in {"workspace.exec", "workspace.profile"}:
            command = arguments["command"]
            if isinstance(command, list):
                rendered = " ".join(shlex.quote(str(item)) for item in command)
            else:
                rendered = str(command)
            result = sandbox.commands.run(rendered, cwd="/opt/lda/work", timeout=int(arguments.get("timeout_seconds", 900)))
            response = _command_result(result)
            self.redactor.assert_clean(json.dumps(response))
            return response
        if tool == "workspace.git_diff":
            base = shlex.quote(str(arguments["base_commit"]))
            result = sandbox.commands.run(f"git -C /opt/lda/work diff --binary {base}..HEAD")
            return _command_result(result)
        raise KeyError(tool)


def _command_result(result: Any) -> dict[str, Any]:
    return {
        "exit_code": int(result.exit_code),
        "stdout": str(result.stdout),
        "stderr": str(result.stderr),
    }


def serve(registry: Path, artifacts: Path, host: str, port: int) -> None:
    gateway = ToolGateway(registry, ArtifactStore(artifacts), CapabilityAuthority.from_environment())

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self) -> None:
            if self.path != "/tool":
                self.send_error(404)
                return
            try:
                length = int(self.headers.get("Content-Length", "0"))
                request = json.loads(self.rfile.read(length))
                token = self.headers.get("Authorization", "").removeprefix("Bearer ")
                response = gateway.invoke(token, request["tool"], request.get("arguments", {}))
                payload = json.dumps({"ok": True, "result": response}).encode()
                self.send_response(200)
            except Exception as error:
                payload = json.dumps({"ok": False, "error": f"{type(error).__name__}: {error}"}).encode()
                self.send_response(403 if isinstance(error, PermissionError) else 400)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

        def log_message(self, format: str, *args: object) -> None:
            return

    ThreadingHTTPServer((host, port), Handler).serve_forever()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--registry", type=Path, required=True)
    parser.add_argument("--artifacts", type=Path, required=True)
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=8090)
    args = parser.parse_args()
    serve(args.registry, args.artifacts, args.host, args.port)


if __name__ == "__main__":
    main()
