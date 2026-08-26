"""Small in-sandbox Responses-to-Chat-Completions adapter.

Fact-Lab's Chat Completions endpoint is reachable from E2B where its
Responses endpoint can exceed the shared gateway response limit.  The bridge
keeps the Codex CLI contract local and never logs the bearer token.
"""

from __future__ import annotations

import argparse
import json
import os
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from uuid import uuid4


def _chat_request(value: dict) -> dict:
    prompt = value.get("input", "")
    if isinstance(prompt, list):
        parts: list[str] = []
        for item in prompt:
            if isinstance(item, dict):
                content = item.get("content", item.get("text", ""))
                if isinstance(content, list):
                    parts.extend(str(x.get("text", "")) for x in content if isinstance(x, dict))
                else:
                    parts.append(str(content))
        prompt = "\n".join(parts)
    messages = []
    if value.get("instructions"):
        messages.append({"role": "system", "content": str(value["instructions"])})
    messages.append({"role": "user", "content": str(prompt)})
    request = {
        "model": value.get("model", "gpt-5.5"),
        "messages": messages,
        "stream": False,
    }
    text_config = value.get("text") or {}
    response_format = text_config.get("format") if isinstance(text_config, dict) else None
    if isinstance(response_format, dict):
        format_type = response_format.get("type")
        if format_type == "json_schema":
            request["response_format"] = {
                "type": "json_schema",
                "json_schema": {
                    "name": response_format.get("name", "structured_output"),
                    "strict": response_format.get("strict", True),
                    "schema": response_format.get("schema", {}),
                },
            }
        elif format_type == "json_object":
            request["response_format"] = {"type": "json_object"}
    for source, target in (("max_output_tokens", "max_tokens"), ("temperature", "temperature")):
        if source in value:
            request[target] = value[source]
    return request


def _responses_response(value: dict) -> dict:
    choice = (value.get("choices") or [{}])[0]
    message = choice.get("message") or {}
    text = message.get("content", "")
    if isinstance(text, list):
        text = "".join(str(item.get("text", "")) for item in text if isinstance(item, dict))
    response_id = f"resp_bridge_{uuid4().hex}"
    chat_usage = value.get("usage") or {}
    usage = {
        "input_tokens": chat_usage.get("prompt_tokens", 0),
        "output_tokens": chat_usage.get("completion_tokens", 0),
        "total_tokens": chat_usage.get("total_tokens", 0),
    }
    return {
        "id": response_id,
        "object": "response",
        "created_at": value.get("created", 0),
        "status": "completed",
        "output": [{
            "id": f"msg_{uuid4().hex}",
            "type": "message",
            "role": "assistant",
            "status": "completed",
            "content": [{"type": "output_text", "text": str(text), "annotations": []}],
        }],
        "usage": usage,
        "error": None,
    }


def _stream_events(response: dict) -> bytes:
    output = response["output"][0]
    item_id = output["id"]
    text = output["content"][0]["text"]
    events = [
        {"type": "response.created", "response": {"id": response["id"], "object": "response", "status": "in_progress", "output": []}},
        {"type": "response.output_item.added", "item": {"id": item_id, "type": "message", "role": "assistant", "status": "in_progress", "content": []}, "output_index": 0},
        {"type": "response.content_part.added", "part": {"type": "output_text", "text": "", "annotations": []}, "item_id": item_id, "output_index": 0, "content_index": 0},
        {"type": "response.output_text.delta", "delta": text, "item_id": item_id, "output_index": 0, "content_index": 0},
        {"type": "response.output_text.done", "text": text, "item_id": item_id, "output_index": 0, "content_index": 0},
        {"type": "response.content_part.done", "part": {"type": "output_text", "text": text, "annotations": []}, "item_id": item_id, "output_index": 0, "content_index": 0},
        {"type": "response.output_item.done", "item": output, "output_index": 0},
        {"type": "response.completed", "response": response},
    ]
    return b"".join(f"event: {event['type']}\ndata: {json.dumps(event)}\n\n".encode() for event in events)


class _Handler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:  # noqa: N802
        if self.path != "/health":
            self.send_error(404)
            return
        payload = b"ok\n"
        self.send_response(200)
        self.send_header("Content-Type", "text/plain")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def do_POST(self) -> None:  # noqa: N802
        if self.path.rstrip("/") != "/v1/responses":
            self.send_error(404)
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
            request = json.loads(self.rfile.read(length))
            endpoint = os.environ.get("LDA_CODEX_CHAT_URL", "https://gpt.fact-lab.work/v1/chat/completions")
            token = os.environ.get("LDA_CODEX_API_KEY", "")
            outgoing = urllib.request.Request(
                endpoint,
                data=json.dumps(_chat_request(request)).encode(),
                headers={
                    "Authorization": f"Bearer {token}",
                    "Content-Type": "application/json",
                    "User-Agent": "lda-codex-bridge/1.0",
                },
                method="POST",
            )
            with urllib.request.urlopen(outgoing, timeout=300) as response:
                result = _responses_response(json.loads(response.read()))
            payload = _stream_events(result) if request.get("stream", False) else json.dumps(result).encode()
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream" if request.get("stream", False) else "application/json")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)
        except Exception as error:
            payload = json.dumps({"error": {"message": f"bridge request failed: {type(error).__name__}"}}).encode()
            self.send_response(502)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

    def log_message(self, _format: str, *_args: object) -> None:
        return


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8787)
    args = parser.parse_args()
    ThreadingHTTPServer((args.host, args.port), _Handler).serve_forever()


if __name__ == "__main__":
    main()
