from __future__ import annotations

import json
import os
import sys
import urllib.request

from lda.gateway.capabilities import ROLE_TOOLS


def _schema(tool: str) -> dict:
    if tool == "workspace.read":
        properties = {"path": {"type": "string"}}
        required = ["path"]
    elif tool == "workspace.write":
        properties = {"path": {"type": "string"}, "content": {"type": "string"}}
        required = ["path", "content"]
    elif tool == "workspace.apply_patch":
        properties = {"patch": {"type": "string"}}
        required = ["patch"]
    elif tool in {"workspace.exec", "workspace.profile"}:
        properties = {
            "command": {"oneOf": [{"type": "string"}, {"type": "array", "items": {"type": "string"}}]},
            "timeout_seconds": {"type": "integer", "minimum": 1, "maximum": 3600},
        }
        required = ["command"]
    elif tool == "workspace.git_diff":
        properties = {"base_commit": {"type": "string"}}
        required = ["base_commit"]
    elif tool == "artifact.publish":
        properties = {"content": {"type": "string"}}
        required = ["content"]
    else:
        properties = {"ref": {"type": "string"}}
        required = ["ref"]
    return {
        "name": tool,
        "description": f"Scoped LDA capability: {tool}",
        "inputSchema": {
            "type": "object",
            "properties": properties,
            "required": required,
            "additionalProperties": False,
        },
    }


def _call(tool: str, arguments: dict) -> dict:
    gateway = os.environ["LDA_GATEWAY_URL"].rstrip("/") + "/tool"
    token = os.environ["LDA_CAPABILITY_TOKEN"]
    request = urllib.request.Request(
        gateway,
        data=json.dumps({"tool": tool, "arguments": arguments}).encode(),
        headers={"Content-Type": "application/json", "Authorization": f"Bearer {token}"},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=300) as response:
        value = json.loads(response.read())
    if not value.get("ok"):
        raise RuntimeError(value.get("error", "tool gateway failed"))
    return value["result"]


def main() -> None:
    role = os.environ["LDA_AGENT_ROLE"]
    tools = sorted(ROLE_TOOLS[role])
    for raw in sys.stdin:
        try:
            request = json.loads(raw)
            method = request.get("method")
            if method == "initialize":
                result = {
                    "protocolVersion": "2025-06-18",
                    "capabilities": {"tools": {}},
                    "serverInfo": {"name": "lda-scoped-tools", "version": "0.2.1"},
                }
            elif method == "notifications/initialized":
                continue
            elif method == "tools/list":
                result = {"tools": [_schema(tool) for tool in tools]}
            elif method == "tools/call":
                name = request["params"]["name"]
                if name not in tools:
                    raise PermissionError(name)
                value = _call(name, request["params"].get("arguments", {}))
                result = {"content": [{"type": "text", "text": json.dumps(value)}]}
            else:
                result = {}
            response = {"jsonrpc": "2.0", "id": request.get("id"), "result": result}
        except Exception as error:
            response = {
                "jsonrpc": "2.0",
                "id": request.get("id") if "request" in locals() else None,
                "error": {"code": -32000, "message": f"{type(error).__name__}: {error}"},
            }
        sys.stdout.write(json.dumps(response) + "\n")
        sys.stdout.flush()


if __name__ == "__main__":
    main()
