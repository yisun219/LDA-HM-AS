from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path
from uuid import uuid4

from lda.models import AgentResult


async def execute(request_path: Path) -> AgentResult:
    from openai_codex import AsyncCodex, CodexConfig, Sandbox
    from openai_codex.types import ReasoningEffort

    request = json.loads(request_path.read_text(encoding="utf-8"))
    trace_path = request_path.with_suffix(".trace.jsonl")
    config = CodexConfig(cwd="/opt/lda/work")
    async with AsyncCodex(config=config) as codex:
        if request.get("thread_id"):
            thread = await codex.thread_resume(
                request["thread_id"],
                cwd="/opt/lda/work",
                model=request["model"],
                sandbox=Sandbox.read_only,
            )
        else:
            thread = await codex.thread_start(
                cwd="/opt/lda/work",
                model=request["model"],
                sandbox=Sandbox.read_only,
            )
        turn = await thread.run(
            request["prompt"],
            effort=ReasoningEffort(request["reasoning_effort"]),
            model=request["model"],
            output_schema=request["schema"],
            sandbox=Sandbox.read_only,
        )
    if not turn.final_response:
        raise RuntimeError("Codex SDK returned no final structured response")
    output = json.loads(turn.final_response)
    with trace_path.open("w", encoding="utf-8") as stream:
        for item in turn.items:
            if hasattr(item, "model_dump_json"):
                stream.write(item.model_dump_json() + "\n")
            else:
                stream.write(json.dumps(item, default=str) + "\n")
    usage = 0
    if turn.usage is not None:
        usage_value = turn.usage.model_dump() if hasattr(turn.usage, "model_dump") else {}
        usage = int(usage_value.get("total_tokens", 0) or 0)
    return AgentResult(
        agent_id=turn.id or uuid4().hex,
        thread_id=thread.id,
        output=output,
        trace_ref=str(trace_path),
        usage_tokens=usage,
    )


def main() -> None:
    if len(sys.argv) != 2:
        raise SystemExit("usage: python -m lda.codex.sdk_runner REQUEST.json")
    print(asyncio.run(execute(Path(sys.argv[1]))).model_dump_json())


if __name__ == "__main__":
    main()
