import importlib

from e2b.connection_config import ConnectionConfig


def test_shared_gateway_preserves_headers(monkeypatch) -> None:
    monkeypatch.setenv("E2B_API_URL", "https://same")
    monkeypatch.setenv("E2B_SANDBOX_URL", "https://same")
    module = importlib.import_module("lda.e2b.shared_gateway")
    module._PATCHED = False
    module.configure_shared_gateway()
    config = ConnectionConfig(
        api_key="e2b_test_key_1234567890",
        validate_api_key=False,
        extra_sandbox_headers={
            "E2b-Sandbox-Id": "sandbox",
            "E2b-Sandbox-Port": "1234",
            "X-Access-Token": "access",
        },
    )
    headers = config.sandbox_headers
    assert headers["X-API-KEY"] == "e2b_test_key_1234567890"
    assert headers["E2b-Sandbox-Id"] == "sandbox"
    assert headers["E2b-Sandbox-Port"] == "1234"
    assert headers["X-Access-Token"] == "access"
    assert module.configure_shared_gateway()
