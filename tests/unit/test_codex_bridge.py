from lda.codex.bridge import _chat_request


def test_responses_json_schema_is_forwarded_to_chat_completions() -> None:
    schema = {
        "type": "object",
        "properties": {"ok": {"type": "boolean"}},
        "required": ["ok"],
        "additionalProperties": False,
    }
    request = _chat_request({
        "model": "gpt-5.6-sol",
        "input": "return JSON",
        "text": {
            "format": {
                "type": "json_schema",
                "name": "agent_result",
                "strict": True,
                "schema": schema,
            }
        },
    })
    assert request["response_format"] == {
        "type": "json_schema",
        "json_schema": {"name": "agent_result", "strict": True, "schema": schema},
    }
