from __future__ import annotations

import asyncio
import ipaddress
import posixpath
import socket
from urllib.parse import SplitResult, urlsplit, urlunsplit


class URLPolicyError(ValueError):
    """A URL is outside the public, read-only capture boundary."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


class PublicURLPolicy:
    """Allow only credential-free HTTP(S) URLs resolving to public IP space."""

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
        if any(not address.is_global for address in addresses):
            raise URLPolicyError("private_address", "Local and private targets are blocked.")

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
