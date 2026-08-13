from __future__ import annotations

import hashlib
import time

from agentictools.adapters.base import AdapterFailure, CaptureAdapter, CaptureDocument
from agentictools.adapters.crawl4ai import Crawl4AIAdapter
from agentictools.archive import MarkdownArchive
from agentictools.discovery import discover_links
from agentictools.models import (
    ArchiveSearchResult,
    FailureDetail,
    PageReadResult,
    PageSaveRequest,
    PageSaveResult,
    SiteDiscoveryResult,
)
from agentictools.url_policy import PublicURLPolicy, URLPolicyError


class AgentWebArchiveService:
    """Shared service layer used by every protocol adapter."""

    def __init__(
        self,
        adapter: CaptureAdapter | None = None,
        url_policy: PublicURLPolicy | None = None,
        archive: MarkdownArchive | None = None,
    ) -> None:
        self.url_policy = url_policy or PublicURLPolicy()
        self.adapter = adapter or Crawl4AIAdapter(self.url_policy)
        self.archive = archive or MarkdownArchive(url_policy=self.url_policy)

    async def page_read(self, url: str) -> PageReadResult:
        started = time.perf_counter()
        normalized, failure = await self._validate(url)
        if failure is not None:
            return PageReadResult(
                success=False,
                original_url=url,
                adapter=self.adapter.name,
                elapsed_ms=self._elapsed(started),
                failure=failure,
            )

        try:
            document = await self.adapter.read(normalized)
            final_url = await self.url_policy.validate(document.final_url)
        except URLPolicyError as exc:
            return self._page_failure(
                normalized,
                started,
                FailureDetail(code=exc.code, message=str(exc), retryable=False),
            )
        except AdapterFailure as exc:
            return self._page_failure(
                normalized,
                started,
                FailureDetail(code=exc.code, message=exc.message, retryable=exc.retryable),
                status_code=exc.status_code,
            )

        markdown = document.markdown.strip()
        if not markdown:
            return self._page_failure(
                normalized,
                started,
                FailureDetail(
                    code="empty_content",
                    message="The page produced no Markdown content.",
                    retryable=False,
                ),
                status_code=document.status_code,
                final_url=final_url,
            )

        digest = hashlib.sha256(markdown.encode("utf-8")).hexdigest()
        return PageReadResult(
            success=True,
            original_url=normalized,
            final_url=final_url,
            title=document.title,
            published_at=document.published_at,
            author=document.author,
            markdown=markdown,
            content_hash=f"sha256:{digest}",
            adapter=document.adapter,
            elapsed_ms=document.elapsed_ms,
            status_code=document.status_code,
        )

    async def site_discover(self, url: str) -> SiteDiscoveryResult:
        started = time.perf_counter()
        normalized, failure = await self._validate(url)
        if failure is not None:
            return SiteDiscoveryResult(
                success=False,
                original_url=url,
                adapter=self.adapter.name,
                elapsed_ms=self._elapsed(started),
                failure=failure,
            )

        try:
            document = await self.adapter.read(normalized)
            final_url = await self.url_policy.validate(document.final_url)
        except URLPolicyError as exc:
            return self._discovery_failure(
                normalized,
                started,
                FailureDetail(code=exc.code, message=str(exc), retryable=False),
            )
        except AdapterFailure as exc:
            return self._discovery_failure(
                normalized,
                started,
                FailureDetail(code=exc.code, message=exc.message, retryable=exc.retryable),
                status_code=exc.status_code,
            )

        navigation, feeds, sitemaps, internal = discover_links(document.html, final_url)
        return SiteDiscoveryResult(
            success=True,
            original_url=normalized,
            final_url=final_url,
            title=document.title,
            navigation=navigation,
            feed_urls=feeds,
            sitemap_urls=sitemaps,
            internal_links=internal,
            adapter=document.adapter,
            elapsed_ms=document.elapsed_ms,
            status_code=document.status_code,
        )

    async def _validate(self, url: str) -> tuple[str, FailureDetail | None]:
        try:
            return await self.url_policy.validate(url), None
        except URLPolicyError as exc:
            return url, FailureDetail(code=exc.code, message=str(exc), retryable=False)

    def _page_failure(
        self,
        original_url: str,
        started: float,
        failure: FailureDetail,
        *,
        status_code: int | None = None,
        final_url: str | None = None,
    ) -> PageReadResult:
        return PageReadResult(
            success=False,
            original_url=original_url,
            final_url=final_url,
            adapter=self.adapter.name,
            elapsed_ms=self._elapsed(started),
            status_code=status_code,
            failure=failure,
        )

    async def page_save(self, request: PageSaveRequest) -> PageSaveResult:
        return await self.archive.save(request)

    def archive_search(
        self,
        *,
        query: str | None = None,
        source: str | None = None,
        tags: list[str] | None = None,
        captured_after: str | None = None,
        captured_before: str | None = None,
        content_hash: str | None = None,
        limit: int = 20,
    ) -> ArchiveSearchResult:
        return self.archive.search(
            query=query,
            source=source,
            tags=tags,
            captured_after=captured_after,
            captured_before=captured_before,
            content_hash=content_hash,
            limit=limit,
        )

    def archive_read(self, document_id: str) -> str:
        return self.archive.read_document(document_id)

    def _discovery_failure(
        self,
        original_url: str,
        started: float,
        failure: FailureDetail,
        *,
        status_code: int | None = None,
    ) -> SiteDiscoveryResult:
        return SiteDiscoveryResult(
            success=False,
            original_url=original_url,
            adapter=self.adapter.name,
            elapsed_ms=self._elapsed(started),
            status_code=status_code,
            failure=failure,
        )

    @staticmethod
    def _elapsed(started: float) -> int:
        return round((time.perf_counter() - started) * 1000)
