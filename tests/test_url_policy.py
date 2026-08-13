from __future__ import annotations

import socket

import pytest

from agentictools.url_policy import PublicURLPolicy, URLPolicyError


@pytest.mark.asyncio
async def test_normalizes_public_http_url(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        socket,
        "getaddrinfo",
        lambda *_args, **_kwargs: [
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", 443))
        ],
    )

    normalized = await PublicURLPolicy().validate(
        "HTTPS://Example.COM:443/news/../story?a=1#section"
    )

    assert normalized == "https://example.com/story?a=1"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("url", "code"),
    [
        ("file:///etc/passwd", "unsupported_scheme"),
        ("https://user:secret@example.com/", "embedded_credentials"),
        ("http://127.0.0.1/admin", "private_address"),
        ("http://169.254.169.254/latest/meta-data", "private_address"),
        ("http://localhost:8080/", "private_address"),
    ],
)
async def test_rejects_non_public_targets(url: str, code: str) -> None:
    with pytest.raises(URLPolicyError) as raised:
        await PublicURLPolicy().validate(url)

    assert raised.value.code == code


@pytest.mark.asyncio
async def test_rejects_hostnames_resolving_to_private_addresses(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        socket,
        "getaddrinfo",
        lambda *_args, **_kwargs: [
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("10.0.0.7", 443))
        ],
    )

    with pytest.raises(URLPolicyError) as raised:
        await PublicURLPolicy().validate("https://internal.example/")

    assert raised.value.code == "private_address"
