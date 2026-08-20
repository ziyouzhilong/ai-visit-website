from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
import re
import time
import urllib.error
import urllib.request
from urllib.parse import urljoin, urlsplit, urlunsplit
import xml.etree.ElementTree as ET

from agentictools.models import LinkEvidence
from agentictools.url_policy import PublicURLPolicy, URLPolicyError


_MAX_RESPONSE_BYTES = 5 * 1024 * 1024
_SITEMAP_LINE = re.compile(r"^\s*sitemap\s*:\s*(\S+)\s*$", re.IGNORECASE)


@dataclass
class SitemapDiscoveryDocument:
    final_url: str
    sitemap_urls: list[str] = field(default_factory=list)
    internal_links: list[LinkEvidence] = field(default_factory=list)
    status_code: int = 200


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *_args: object, **_kwargs: object) -> None:
        return None


class RobotsSitemapDiscovery:
    """Recover public link evidence from robots-declared sitemaps."""

    name = "robots-sitemap"

    def __init__(
        self,
        url_policy: PublicURLPolicy,
        *,
        max_sitemap_documents: int = 12,
        max_links: int = 500,
        cache_ttl_seconds: int = 300,
    ) -> None:
        self.url_policy = url_policy
        self.max_sitemap_documents = max_sitemap_documents
        self.max_links = max_links
        self.cache_ttl_seconds = cache_ttl_seconds
        self._site_cache: dict[
            str, tuple[float, list[str], list[LinkEvidence]]
        ] = {}

    async def discover(self, entry_url: str) -> SitemapDiscoveryDocument | None:
        parsed = urlsplit(entry_url)
        origin = urlunsplit((parsed.scheme, parsed.netloc, "/", "", ""))
        cached = self._site_cache.get(origin)
        if cached is not None and time.monotonic() - cached[0] <= self.cache_ttl_seconds:
            return self._document_for_entry(entry_url, parsed.path, cached[1], cached[2])
        robots_url = urlunsplit((parsed.scheme, parsed.netloc, "/robots.txt", "", ""))
        robots = await self._fetch(robots_url)
        if robots is None:
            return None
        _status, robots_final_url, robots_body = robots
        try:
            robots_text = robots_body.decode("utf-8", "replace")
        except UnicodeError:
            return None

        declared = []
        for line in robots_text.splitlines():
            match = _SITEMAP_LINE.match(line)
            if not match:
                continue
            candidate = urljoin(robots_final_url, match.group(1))
            try:
                candidate = await self.url_policy.validate(candidate)
            except URLPolicyError:
                continue
            if candidate not in declared:
                declared.append(candidate)
        if not declared:
            return None

        # News sitemaps usually place the newest article URLs first, which is the
        # most useful bounded fallback when a section page presents a challenge.
        queue = sorted(declared, key=lambda value: ("news" not in value.lower(), value))
        seen_documents: set[str] = set()
        exposed_sitemaps = list(declared)
        links: list[LinkEvidence] = []
        seen_links: set[str] = set()
        entry_host = (parsed.hostname or "").lower()
        entry_path = parsed.path.rstrip("/") + "/"

        while (
            queue
            and len(seen_documents) < self.max_sitemap_documents
            and len(links) < self.max_links
        ):
            sitemap_url = queue.pop(0)
            if sitemap_url in seen_documents:
                continue
            seen_documents.add(sitemap_url)
            fetched = await self._fetch(sitemap_url)
            if fetched is None:
                continue
            _status, _final_url, body = fetched
            parsed_sitemap = self._parse_sitemap(body)
            if parsed_sitemap is None:
                continue
            kind, entries = parsed_sitemap
            if kind == "sitemapindex":
                children = []
                for url, _title, _published, _lastmod in entries:
                    try:
                        normalized = await self.url_policy.validate(url)
                    except URLPolicyError:
                        continue
                    if normalized not in seen_documents and normalized not in queue:
                        children.append(normalized)
                queue = children + queue
                continue

            for url, title, published, lastmod in entries:
                normalized = self._normalize_same_site_url(url, entry_host)
                if normalized is None or normalized in seen_links:
                    continue
                seen_links.add(normalized)
                context_parts = ["Discovered in a public sitemap."]
                if published:
                    context_parts.append(f"Published: {published}.")
                elif lastmod:
                    context_parts.append(f"Last modified: {lastmod}.")
                links.append(
                    LinkEvidence(
                        url=normalized,
                        anchor_text=title or normalized,
                        surrounding_text=" ".join(context_parts),
                        published_at=published or lastmod,
                        inferred_type="article" if title else "sitemap",
                    )
                )
                if len(links) >= self.max_links:
                    break

        if not links:
            return None
        self._site_cache[origin] = (time.monotonic(), exposed_sitemaps, links)
        return self._document_for_entry(entry_url, entry_path, exposed_sitemaps, links)

    @staticmethod
    def _document_for_entry(
        entry_url: str,
        entry_path: str,
        sitemap_urls: list[str],
        links: list[LinkEvidence],
    ) -> SitemapDiscoveryDocument:
        normalized_entry_path = entry_path.rstrip("/") + "/"
        selected = links
        if normalized_entry_path != "/":
            section_links = [
                item
                for item in links
                if urlsplit(item.url).path.startswith(normalized_entry_path)
            ]
            if section_links:
                selected = section_links
        return SitemapDiscoveryDocument(
            final_url=entry_url,
            sitemap_urls=list(sitemap_urls),
            internal_links=list(selected),
        )

    async def _fetch(self, url: str) -> tuple[int, str, bytes] | None:
        current = url
        for _redirect in range(6):
            try:
                current = await self.url_policy.validate(current)
            except URLPolicyError:
                return None
            status, headers, body = await asyncio.to_thread(self._request_once, current)
            if status in {301, 302, 303, 307, 308}:
                location = headers.get("location")
                if not location:
                    return None
                current = urljoin(current, location)
                continue
            if status != 200 or len(body) > _MAX_RESPONSE_BYTES:
                return None
            try:
                final_url = await self.url_policy.validate(current)
            except URLPolicyError:
                return None
            return status, final_url, body
        return None

    @staticmethod
    def _request_once(url: str) -> tuple[int, dict[str, str], bytes]:
        opener = urllib.request.build_opener(_NoRedirect())
        request = urllib.request.Request(
            url,
            headers={
                "Accept": "application/xml,text/xml,text/plain;q=0.9,*/*;q=0.1",
                "User-Agent": "AI-Visit-Website/0.2",
            },
        )
        try:
            with opener.open(request, timeout=20) as response:
                return (
                    response.status,
                    {key.lower(): value for key, value in response.headers.items()},
                    response.read(_MAX_RESPONSE_BYTES + 1),
                )
        except urllib.error.HTTPError as exc:
            return (
                exc.code,
                {key.lower(): value for key, value in exc.headers.items()},
                exc.read(_MAX_RESPONSE_BYTES + 1),
            )
        except (OSError, ValueError):
            return 0, {}, b""

    @staticmethod
    def _parse_sitemap(
        body: bytes,
    ) -> tuple[str, list[tuple[str, str | None, str | None, str | None]]] | None:
        try:
            root = ET.fromstring(body)
        except ET.ParseError:
            return None
        kind = RobotsSitemapDiscovery._local_name(root.tag)
        if kind not in {"sitemapindex", "urlset"}:
            return None

        entries = []
        expected_child = "sitemap" if kind == "sitemapindex" else "url"
        for child in root:
            if RobotsSitemapDiscovery._local_name(child.tag) != expected_child:
                continue
            loc = RobotsSitemapDiscovery._direct_text(child, "loc")
            if not loc:
                continue
            title = RobotsSitemapDiscovery._descendant_text(child, "title")
            published = RobotsSitemapDiscovery._descendant_text(child, "publication_date")
            lastmod = RobotsSitemapDiscovery._direct_text(child, "lastmod")
            entries.append((loc.strip(), title, published, lastmod))
        return kind, entries

    @staticmethod
    def _direct_text(node: ET.Element, name: str) -> str | None:
        for child in node:
            if RobotsSitemapDiscovery._local_name(child.tag) == name and child.text:
                return child.text.strip()
        return None

    @staticmethod
    def _descendant_text(node: ET.Element, name: str) -> str | None:
        for child in node.iter():
            if RobotsSitemapDiscovery._local_name(child.tag) == name and child.text:
                return child.text.strip()
        return None

    @staticmethod
    def _local_name(tag: str) -> str:
        return tag.rsplit("}", 1)[-1].lower()

    @staticmethod
    def _normalize_same_site_url(url: str, entry_host: str) -> str | None:
        try:
            parsed = urlsplit(url.strip())
        except ValueError:
            return None
        if (
            parsed.scheme.lower() not in {"http", "https"}
            or not parsed.hostname
            or parsed.username is not None
            or parsed.password is not None
            or parsed.hostname.rstrip(".").lower() != entry_host
        ):
            return None
        return urlunsplit(
            (parsed.scheme.lower(), parsed.netloc.lower(), parsed.path or "/", parsed.query, "")
        )
