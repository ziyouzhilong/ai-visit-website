from __future__ import annotations

import asyncio
import ipaddress
import json
import os
import posixpath
import socket
import urllib.parse
import urllib.request
from urllib.parse import SplitResult, urlsplit, urlunsplit


class URLPolicyError(ValueError):
    """A URL is outside the public, read-only capture boundary."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


class PublicURLPolicy:
    """Allow only credential-free HTTP(S) URLs resolving to public IP space."""

    _PROXY_FAKE_IP_NETWORK = ipaddress.ip_network("198.18.0.0/15")

    def __init__(self, *, public_dns_fallback: bool | None = None) -> None:
        if public_dns_fallback is None:
            public_dns_fallback = (
                os.environ.get("AI_VISIT_WEBSITE_PUBLIC_DNS_FALLBACK", "0") == "1"
            )
        self.public_dns_fallback = public_dns_fallback
        self._public_dns_cache: dict[str, list[ipaddress.IPv4Address | ipaddress.IPv6Address]] = {}

    async def validate(self, url: str) -> str:
        try:
            parsed = urlsplit(url.strip())
        except ValueError as exc:
            raise URLPolicyError("invalid_url", "The URL could not be parsed.") from exc

        scheme = parsed.scheme.lower()
        if scheme not in {"http", "https"}:
            raise URLPolicyError(
                "unsupported_scheme", "Only public HTTP and HTTPS URLs are supported."
            )
        if parsed.username is not None or parsed.password is not None:
            raise URLPolicyError(
                "embedded_credentials", "URLs containing credentials are not accepted."
            )

        hostname = parsed.hostname
        if not hostname:
            raise URLPolicyError("invalid_url", "The URL must include a hostname.")
        hostname = hostname.rstrip(".").lower()
        if hostname == "localhost" or hostname.endswith((".localhost", ".local")):
            raise URLPolicyError("private_address", "Local and private targets are blocked.")

        try:
            port = parsed.port
        except ValueError as exc:
            raise URLPolicyError("invalid_url", "The URL contains an invalid port.") from exc

        await self._require_public_resolution(hostname, port or (443 if scheme == "https" else 80))

        try:
            ascii_hostname = hostname.encode("idna").decode("ascii")
        except UnicodeError as exc:
            raise URLPolicyError("invalid_url", "The hostname is invalid.") from exc

        netloc = f"[{ascii_hostname}]" if ":" in ascii_hostname else ascii_hostname
        if port is not None and not (
            (scheme == "https" and port == 443) or (scheme == "http" and port == 80)
        ):
            netloc = f"{netloc}:{port}"

        path = self._normalize_path(parsed.path)
        normalized = SplitResult(scheme, netloc, path, parsed.query, "")
        return urlunsplit(normalized)

    async def _require_public_resolution(self, hostname: str, port: int) -> None:
        try:
            direct_ip = ipaddress.ip_address(hostname)
        except ValueError:
            direct_ip = None

        if direct_ip is not None:
            addresses = [direct_ip]
        else:
            try:
                records = await asyncio.to_thread(
                    socket.getaddrinfo,
                    hostname,
                    port,
                    type=socket.SOCK_STREAM,
                )
            except socket.gaierror as exc:
                raise URLPolicyError("dns_failure", "The hostname could not be resolved.") from exc
            addresses = []
            for record in records:
                address = ipaddress.ip_address(record[4][0])
                if address not in addresses:
                    addresses.append(address)

        if not addresses:
            raise URLPolicyError("dns_failure", "The hostname returned no addresses.")
        if all(address.is_global for address in addresses):
            return

        # Transparent proxies commonly synthesize RFC 2544 benchmark addresses for
        # public hostnames. Never trust that range by itself: when explicitly enabled,
        # independently confirm that public DNS resolves the hostname only to global
        # addresses. Literal 198.18.0.0/15 URLs remain blocked.
        can_verify_proxy_fake_ip = (
            direct_ip is None
            and self.public_dns_fallback
            and all(address in self._PROXY_FAKE_IP_NETWORK for address in addresses)
        )
        if can_verify_proxy_fake_ip:
            public_addresses = await self._resolve_public_dns(hostname)
            if public_addresses and all(address.is_global for address in public_addresses):
                return

        raise URLPolicyError("private_address", "Local and private targets are blocked.")

    async def _resolve_public_dns(
        self, hostname: str
    ) -> list[ipaddress.IPv4Address | ipaddress.IPv6Address]:
        cached = self._public_dns_cache.get(hostname)
        if cached is not None:
            return cached

        addresses = await asyncio.to_thread(self._resolve_public_dns_sync, hostname)
        self._public_dns_cache[hostname] = addresses
        return addresses

    @staticmethod
    def _resolve_public_dns_sync(
        hostname: str,
    ) -> list[ipaddress.IPv4Address | ipaddress.IPv6Address]:
        addresses: list[ipaddress.IPv4Address | ipaddress.IPv6Address] = []
        for record_type in ("A", "AAAA"):
            query = urllib.parse.urlencode({"name": hostname, "type": record_type})
            request = urllib.request.Request(
                f"https://dns.google/resolve?{query}",
                headers={
                    "Accept": "application/dns-json",
                    "User-Agent": "AI-Visit-Website/0.2",
                },
            )
            try:
                with urllib.request.urlopen(request, timeout=10) as response:
                    payload = response.read(131_073)
            except (OSError, ValueError):
                continue
            if len(payload) > 131_072:
                continue
            try:
                document = json.loads(payload)
            except (json.JSONDecodeError, UnicodeDecodeError):
                continue
            if document.get("Status") != 0:
                continue
            expected_type = 1 if record_type == "A" else 28
            for answer in document.get("Answer", []):
                if answer.get("type") != expected_type:
                    continue
                try:
                    address = ipaddress.ip_address(answer.get("data", ""))
                except ValueError:
                    continue
                if address not in addresses:
                    addresses.append(address)
        return addresses

    @staticmethod
    def _normalize_path(path: str) -> str:
        if not path:
            return "/"
        trailing_slash = path.endswith("/")
        normalized = posixpath.normpath(path)
        if not normalized.startswith("/"):
            normalized = "/" + normalized
        if trailing_slash and normalized != "/":
            normalized += "/"
        return normalized
