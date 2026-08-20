from __future__ import annotations

import socket

import pytest

from agentictools.adapters.crawl4ai import Crawl4AIAdapter
from agentictools.url_policy import PublicURLPolicy


class FakeRequest:
    def __init__(self, url: str) -> None:
        self.url = url


class FakeRoute:
    def __init__(self, url: str) -> None:
        self.request = FakeRequest(url)
        self.action: str | None = None

    async def abort(self, _reason: str = "blockedbyclient") -> None:
        self.action = "abort"

    async def continue_(self) -> None:
        self.action = "continue"


@pytest.mark.asyncio
async def test_browser_route_aborts_private_network_requests(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        socket,
        "getaddrinfo",
        lambda host, *_args, **_kwargs: [
            (
                socket.AF_INET,
                socket.SOCK_STREAM,
                6,
                "",
                (("10.0.0.8" if host == "internal.example" else "93.184.216.34"), 443),
            )
        ],
    )
    handler = Crawl4AIAdapter(PublicURLPolicy())._route_handler
    public_route = FakeRoute("https://example.com/app.js")
    private_route = FakeRoute("https://internal.example/secret")
    data_route = FakeRoute("data:image/png;base64,AAAA")

    await handler(public_route)
    await handler(private_route)
    await handler(data_route)

    assert public_route.action == "continue"
    assert private_route.action == "abort"
    assert data_route.action == "continue"


def test_browser_config_keeps_page_rendering_enabled() -> None:
    config = Crawl4AIAdapter(PublicURLPolicy())._browser_config()

    assert config.text_mode is False


def test_run_config_does_not_enable_destructive_overlay_rewrite() -> None:
    config = Crawl4AIAdapter(PublicURLPolicy())._run_config()

    assert config.remove_overlay_elements is False
    assert config.remove_consent_popups is False
    assert config.remove_forms is True


def test_classifies_automated_access_challenges() -> None:
    code, message, retryable = Crawl4AIAdapter._classify_failure(
        200, "Blocked by anti-bot protection: challenge"
    )

    assert code == "bot_challenge"
    assert "challenge" in message.lower()
    assert retryable is False


def test_challenge_detail_takes_priority_over_unauthorized_status() -> None:
    code, message, retryable = Crawl4AIAdapter._classify_failure(
        401, "Blocked by anti-bot protection: DataDome captcha"
    )

    assert code == "bot_challenge"
    assert "challenge" in message.lower()
    assert retryable is False


def test_robots_detail_takes_priority_over_forbidden_status() -> None:
    code, message, retryable = Crawl4AIAdapter._classify_failure(
        403, "Access denied by robots.txt"
    )

    assert code == "robots_denied"
    assert "robots" in message.lower()
    assert retryable is False
