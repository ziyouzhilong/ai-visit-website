from __future__ import annotations

import pytest
from mcp.client import Client

from agentictools.mcp_server import create_server


def test_mcp_server_exposes_only_milestone_a_tools() -> None:
    server = create_server()
    tools = server._tool_manager.list_tools()

    assert {tool.name for tool in tools} == {"site_discover", "page_read"}
    for tool in tools:
        assert tool.description
        assert tool.parameters.get("type") == "object"
        assert "url" in tool.parameters.get("properties", {})


@pytest.mark.asyncio
async def test_official_mcp_client_discovers_tools_and_calls_structured_failure() -> None:
    server = create_server()

    async with Client(server, mode="legacy") as client:
        listing = await client.list_tools()
        result = await client.call_tool("page_read", {"url": "file:///etc/passwd"})

    assert {tool.name for tool in listing.tools} == {"site_discover", "page_read"}
    assert result.is_error is False
    assert result.structured_content is not None
    assert result.structured_content["success"] is False
    assert result.structured_content["failure"]["code"] == "unsupported_scheme"
