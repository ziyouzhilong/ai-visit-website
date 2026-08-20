from __future__ import annotations

import asyncio
import hashlib
import json
import stat
import urllib.error
import urllib.request
from pathlib import Path

import pytest

from agentictools.browser_bridge import (
    BrowserBridgeHTTPServer,
    BrowserTaskBroker,
    LoopbackBrowserBridgeClient,
    default_bridge_data_dir,
    load_or_create_bridge_token,
)


def request_json(
    endpoint: str,
    path: str,
    *,
    token: str | None,
    payload: dict | None = None,
) -> tuple[int, dict]:
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    request = urllib.request.Request(
        f"{endpoint}{path}",
        data=None if payload is None else json.dumps(payload).encode("utf-8"),
        method="GET" if payload is None else "POST",
        headers=headers,
    )
    with urllib.request.urlopen(request, timeout=5) as response:
        return response.status, json.loads(response.read() or b"{}")


def test_bridge_token_is_persistent_and_owner_only(tmp_path: Path) -> None:
    path = tmp_path / "bridge-token"

    first = load_or_create_bridge_token(path)
    second = load_or_create_bridge_token(path)

    assert first == second
    assert len(first) >= 32
    assert stat.S_IMODE(path.stat().st_mode) == 0o600


def test_bridge_token_directory_is_shared_across_host_data_dirs(
    tmp_path: Path, monkeypatch
) -> None:
    shared = tmp_path / "shared-bridge"
    monkeypatch.setenv("AI_VISIT_WEBSITE_BRIDGE_DATA_DIR", str(shared))
    monkeypatch.setenv("AI_VISIT_WEBSITE_DATA_DIR", str(tmp_path / "host-data"))
    monkeypatch.setenv("AGENTICTOOLS_ARCHIVE_DIR", str(tmp_path / "host-data" / "archive"))

    assert default_bridge_data_dir() == shared


def test_loopback_server_rejects_missing_token() -> None:
    server = BrowserBridgeHTTPServer(port=0, token="test-secret-token")
    server.start()
    try:
        with pytest.raises(urllib.error.HTTPError) as raised:
            request_json(server.endpoint, "/v1/agent/status", token=None)
        assert raised.value.code == 401
    finally:
        server.close()


@pytest.mark.asyncio
async def test_extension_claims_and_completes_a_browser_read() -> None:
    broker = BrowserTaskBroker()
    token = "test-secret-token"
    server = BrowserBridgeHTTPServer(port=0, token=token, broker=broker)
    server.start()
    client = LoopbackBrowserBridgeClient(endpoint=server.endpoint, token=token)
    markdown = "# Example report\n\nImportant article evidence."
    digest = hashlib.sha256(markdown.encode("utf-8")).hexdigest()

    def extension_worker() -> None:
        task = broker.claim_task(wait_seconds=5, extension_version="1.5.0")
        assert task is not None
        assert task["url"] == "https://example.com/report"
        accepted = broker.complete_task(
            task["requestId"],
            {
                "success": True,
                "original_url": task["url"],
                "final_url": task["url"],
                "title": "Example report",
                "markdown": markdown,
                "content_hash": f"sha256:{digest}",
                "adapter": "chrome-extension",
                "elapsed_ms": 35,
                "paragraph_count": 1,
                "article_text_length": 27,
                "selector_strategy": "generic-page-dom",
                "failure": None,
            },
        )
        assert accepted is True

    broker.heartbeat("1.5.0")
    worker = asyncio.create_task(asyncio.to_thread(extension_worker))
    try:
        result = await client.page_read(
            "https://example.com/report",
            purpose="Find material changes",
            timeout_seconds=15,
            request_id="report-1",
        )
        await worker
    finally:
        server.close()

    assert result.success is True
    assert result.request_id == "report-1"
    assert result.markdown == markdown
    assert result.content_hash == f"sha256:{digest}"
    assert result.selector_strategy == "generic-page-dom"


def test_broker_cancels_queued_task_and_does_not_offer_it_to_chrome() -> None:
    broker = BrowserTaskBroker()
    broker.create_task(
        url="https://example.com/report",
        purpose=None,
        timeout_seconds=30,
        request_id="cancel-me",
    )

    assert broker.cancel_task("cancel-me") == "canceled"
    assert broker.claim_task(wait_seconds=0, extension_version="1.5.0") is None
    snapshot = broker.wait_for_task("cancel-me", 0)
    assert snapshot is not None
    assert snapshot["state"] == "canceled"
