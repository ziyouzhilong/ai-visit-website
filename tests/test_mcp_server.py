from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest
from mcp.client import Client

from agentictools.archive import MarkdownArchive
from agentictools.mcp_server import create_server
from agentictools.service import AgentWebArchiveService


class AllowExamplePolicy:
    async def validate(self, url: str) -> str:
        return url.split("#", 1)[0]


def test_mcp_server_exposes_milestone_a_and_b_contracts() -> None:
    server = create_server()
    tools = server._tool_manager.list_tools()

    assert {tool.name for tool in tools} == {
        "site_discover",
        "page_read",
        "page_save",
        "archive_search",
    }
    by_name = {tool.name: tool for tool in tools}
    for tool in by_name.values():
        assert tool.description
        assert tool.parameters.get("type") == "object"
    assert set(by_name["site_discover"].parameters["required"]) == {"url"}
    assert set(by_name["page_read"].parameters["required"]) == {"url"}
    assert set(by_name["page_save"].parameters["required"]) == {
        "source_url",
        "title",
        "markdown",
    }
    assert by_name["page_save"].annotations.idempotent_hint is True
    assert by_name["page_save"].annotations.destructive_hint is False
    assert by_name["archive_search"].annotations.read_only_hint is True


@pytest.mark.asyncio
async def test_official_mcp_client_discovers_tools_and_calls_structured_failure() -> None:
    server = create_server()

    async with Client(server, mode="legacy") as client:
        listing = await client.list_tools()
        result = await client.call_tool("page_read", {"url": "file:///etc/passwd"})

    assert {tool.name for tool in listing.tools} == {
        "site_discover",
        "page_read",
        "page_save",
        "archive_search",
    }
    assert result.is_error is False
    assert result.structured_content is not None
    assert result.structured_content["success"] is False
    assert result.structured_content["failure"]["code"] == "unsupported_scheme"


@pytest.mark.asyncio
async def test_official_mcp_client_saves_deduplicates_searches_and_reads_resource(
    tmp_path: Path,
) -> None:
    archive = MarkdownArchive(
        root=tmp_path / "archive",
        url_policy=AllowExamplePolicy(),
        clock=lambda: datetime(2026, 8, 14, 9, 0, tzinfo=timezone.utc),
    )
    service = AgentWebArchiveService(
        url_policy=AllowExamplePolicy(),
        archive=archive,
    )
    server = create_server(service)
    arguments = {
        "source_url": "https://example.com/report#top",
        "title": "Storage Report",
        "markdown": "# Storage Report\n\nSodium battery capacity increased.",
        "tags": ["Energy", "Storage"],
    }

    async with Client(server, mode="legacy") as client:
        first = await client.call_tool("page_save", arguments)
        second = await client.call_tool("page_save", arguments)
        search = await client.call_tool(
            "archive_search", {"query": "sodium battery", "tags": ["energy"]}
        )
        resource = await client.read_resource(first.structured_content["resource_uri"])

    assert first.is_error is False
    assert first.structured_content["status"] == "saved"
    assert first.content[-1].type == "resource_link"
    assert second.structured_content["status"] == "duplicate"
    assert second.structured_content["document_id"] == first.structured_content["document_id"]
    assert search.structured_content["total"] == 1
    assert search.content[-1].type == "resource_link"
    assert resource.contents[0].mime_type == "text/markdown"
    assert "title: Storage Report" in resource.contents[0].text
    assert resource.contents[0].text.endswith(arguments["markdown"] + "\n")
