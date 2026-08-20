from __future__ import annotations

import asyncio
import hashlib
from datetime import datetime, timezone
from pathlib import Path

import pytest
from mcp.client import Client

from agentictools.archive import MarkdownArchive
from agentictools.mcp_server import create_server
from agentictools.models import (
    BrowserBridgeStatusResult,
    BrowserCancelResult,
    PageReadResult,
)
from agentictools.service import AgentWebArchiveService


class AllowExamplePolicy:
    async def validate(self, url: str) -> str:
        return url.split("#", 1)[0]


class StubBrowserBridge:
    async def status(self) -> BrowserBridgeStatusResult:
        return BrowserBridgeStatusResult(
            success=True,
            configured=True,
            connected=True,
            endpoint="http://127.0.0.1:32145",
            extension_version="1.5.0",
        )

    async def page_read(
        self,
        url: str,
        *,
        purpose: str | None,
        timeout_seconds: int,
        request_id: str | None,
    ) -> PageReadResult:
        markdown = "# Browser evidence\n\nOne authorized article."
        digest = hashlib.sha256(markdown.encode("utf-8")).hexdigest()
        return PageReadResult(
            success=True,
            original_url=url,
            request_id=request_id,
            final_url=url,
            title="Browser evidence",
            markdown=markdown,
            content_hash=f"sha256:{digest}",
            adapter="chrome-extension",
            elapsed_ms=12,
        )

    async def cancel(self, request_id: str) -> BrowserCancelResult:
        return BrowserCancelResult(success=True, request_id=request_id, status="canceled")


EXPECTED_TOOLS = {
    "site_discover",
    "article_list",
    "page_read",
    "browser_status",
    "browser_page_read",
    "browser_cancel",
    "browser_batch_start",
    "browser_batch_status",
    "browser_batch_cancel",
    "page_save",
    "archive_search",
}


def test_mcp_server_exposes_discovery_browser_batch_and_archive_contracts() -> None:
    server = create_server()
    assert server.name == "ai-visit-website"
    assert server.title == "AI Visit website"
    tools = server._tool_manager.list_tools()

    assert {tool.name for tool in tools} == EXPECTED_TOOLS
    by_name = {tool.name: tool for tool in tools}
    for tool in by_name.values():
        assert tool.description
        assert tool.parameters.get("type") == "object"
    assert set(by_name["site_discover"].parameters["required"]) == {"url"}
    assert set(by_name["article_list"].parameters["required"]) == {"url"}
    assert set(by_name["page_read"].parameters["required"]) == {"url"}
    assert set(by_name["browser_page_read"].parameters["required"]) == {"url"}
    assert set(by_name["browser_cancel"].parameters["required"]) == {"request_id"}
    assert set(by_name["browser_batch_start"].parameters["required"]) == {"urls"}
    assert set(by_name["browser_batch_status"].parameters["required"]) == {"run_id"}
    assert set(by_name["browser_batch_cancel"].parameters["required"]) == {"run_id"}
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

    assert {tool.name for tool in listing.tools} == EXPECTED_TOOLS
    assert result.is_error is False
    assert result.structured_content is not None
    assert result.structured_content["success"] is False
    assert result.structured_content["failure"]["code"] == "unsupported_scheme"


@pytest.mark.asyncio
async def test_official_mcp_client_calls_the_paired_browser_contract() -> None:
    service = AgentWebArchiveService(
        url_policy=AllowExamplePolicy(),
        browser_bridge=StubBrowserBridge(),
    )
    server = create_server(service)

    async with Client(server, mode="legacy") as client:
        status = await client.call_tool("browser_status", {})
        read = await client.call_tool(
            "browser_page_read",
            {
                "url": "https://example.com/article#top",
                "purpose": "Prepare a report",
                "timeout_seconds": 30,
                "request_id": "article-1",
            },
        )
        canceled = await client.call_tool("browser_cancel", {"request_id": "article-2"})
        started = await client.call_tool(
            "browser_batch_start",
            {
                "urls": [
                    "https://example.com/one",
                    "https://example.com/two",
                ],
                "purpose": "Prepare a report",
                "run_id": "report-batch",
            },
        )
        for _ in range(20):
            batch = await client.call_tool(
                "browser_batch_status", {"run_id": "report-batch"}
            )
            if batch.structured_content["state"] == "completed":
                break
            await asyncio.sleep(0)

    assert status.structured_content["connected"] is True
    assert status.structured_content["extension_version"] == "1.5.0"
    assert read.structured_content["success"] is True
    assert read.structured_content["original_url"] == "https://example.com/article"
    assert read.structured_content["request_id"] == "article-1"
    assert canceled.structured_content["status"] == "canceled"
    assert started.structured_content["run_id"] == "report-batch"
    assert batch.structured_content["state"] == "completed"
    assert batch.structured_content["succeeded"] == 2


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
