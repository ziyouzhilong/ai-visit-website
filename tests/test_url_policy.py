from __future__ import annotations

import ipaddress
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


@pytest.mark.asyncio
async def test_public_dns_fallback_accepts_verified_proxy_fake_ip(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        socket,
        "getaddrinfo",
        lambda *_args, **_kwargs: [
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("198.18.2.118", 443))
        ],
    )
    policy = PublicURLPolicy(public_dns_fallback=True)

    async def resolve_public_dns(_hostname: str) -> list[ipaddress.IPv4Address]:
        return [ipaddress.ip_address("18.154.144.38")]

    monkeypatch.setattr(policy, "_resolve_public_dns", resolve_public_dns)

    assert await policy.validate("https://www.reuters.com/business/") == (
        "https://www.reuters.com/business/"
    )


@pytest.mark.asyncio
async def test_proxy_fake_ip_stays_blocked_without_public_dns_confirmation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        socket,
        "getaddrinfo",
        lambda *_args, **_kwargs: [
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("198.18.2.118", 443))
        ],
    )

    with pytest.raises(URLPolicyError) as raised:
        await PublicURLPolicy(public_dns_fallback=False).validate(
            "https://www.reuters.com/business/"
        )

    assert raised.value.code == "private_address"


@pytest.mark.asyncio
async def test_literal_proxy_fake_ip_is_never_allowed() -> None:
    with pytest.raises(URLPolicyError) as raised:
        await PublicURLPolicy(public_dns_fallback=True).validate("https://198.18.2.118/")

    assert raised.value.code == "private_address"
