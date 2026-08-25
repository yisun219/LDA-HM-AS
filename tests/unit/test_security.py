import pytest

from lda.fences import scan_trace
from lda.security import SecretRedactor, child_environment


def test_secret_redaction_and_child_environment(tmp_path) -> None:
    source = {
        "E2B_API_KEY": "e2b_private_secret_value_123456",
        "OPENAI_API_KEY": "sk-private-secret-value-123456",
        "PATH": "/bin",
        "LDA_GATEWAY_URL": "https://gateway",
    }
    child = child_environment(source, agent_runtime=True)
    assert set(child) == {"PATH", "LDA_GATEWAY_URL"}
    model_child = child_environment({**source, "LDA_CODEX_API_KEY": "sk-agent-only"}, agent_runtime=True)
    assert model_child["LDA_CODEX_API_KEY"] == "sk-agent-only"
    assert "E2B_API_KEY" not in model_child
    assert "OPENAI_API_KEY" not in model_child
    assert "LDA_CODEX_API_KEY" not in child_environment({"LDA_CODEX_API_KEY": "sk-agent-only"})
    redactor = SecretRedactor(list(source.values()))
    assert "private" not in redactor.redact("token=e2b_private_secret_value_123456")
    with pytest.raises(ValueError):
        redactor.assert_clean("Authorization=e2b_private_secret_value_123456")


def test_anti_cheat_detects_forbidden_actions(tmp_path) -> None:
    trace = tmp_path / "trace.jsonl"
    trace.write_text('{"command":"cc -O3 -march=native x.c"}\n{"command":"export LD_PRELOAD=/tmp/x.so"}\n', encoding="utf-8")
    rules = {finding.rule for finding in scan_trace(trace)}
    assert {"march_native", "undeclared_preload"} <= rules
