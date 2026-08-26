from lda.gateway.mcp import _schema


def test_scoped_mcp_tools_publish_strict_argument_schemas() -> None:
    read = _schema("workspace.read")["inputSchema"]
    execute = _schema("workspace.exec")["inputSchema"]
    artifact = _schema("artifact.read")["inputSchema"]
    assert read["required"] == ["path"]
    assert execute["required"] == ["command"]
    assert artifact["required"] == ["ref"]
    assert not read["additionalProperties"]
