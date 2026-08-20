from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import datetime, timezone
import hashlib
import re
import time
import uuid

from agentictools.adapters.base import AdapterFailure, CaptureAdapter, CaptureDocument
from agentictools.adapters.crawl4ai import Crawl4AIAdapter
from agentictools.archive import MarkdownArchive
from agentictools.browser_bridge import (
    BrowserBridge,
    default_browser_bridge,
    verify_page_result_hash,
)
from agentictools.discovery import discover_links
from agentictools.models import (
    ArticleCandidate,
    ArticleListResult,
    ArchiveSearchResult,
    BrowserBatchItem,
    BrowserBatchStatusResult,
    BrowserBridgeStatusResult,
    BrowserCancelResult,
    FailureDetail,
    PageReadResult,
    PageSaveRequest,
    PageSaveResult,
    SiteDiscoveryResult,
)
from agentictools.sitemap_discovery import RobotsSitemapDiscovery
from agentictools.url_policy import PublicURLPolicy, URLPolicyError


_BATCH_ID = re.compile(r"^[A-Za-z0-9._-]{1,80}$")


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


@dataclass
class _BrowserBatchRun:
    run_id: str
    purpose: str | None
    timeout_seconds: int
    urls: list[str]
    items: list[BrowserBatchItem]
    state: str = "queued"
    started_at: str | None = None
    completed_at: str | None = None
    active_request_id: str | None = None
    cancel_requested: bool = False
    failure: FailureDetail | None = None
    task: asyncio.Task[None] | None = field(default=None, repr=False)


class AgentWebArchiveService:
    """Shared service layer used by every protocol adapter."""

    def __init__(
        self,
        adapter: CaptureAdapter | None = None,
        url_policy: PublicURLPolicy | None = None,
        archive: MarkdownArchive | None = None,
        discovery_fallback: RobotsSitemapDiscovery | None = None,
        browser_bridge: BrowserBridge | None = None,
    ) -> None:
        self.url_policy = url_policy or PublicURLPolicy()
        self.adapter = adapter or Crawl4AIAdapter(self.url_policy)
        self.archive = archive or MarkdownArchive(url_policy=self.url_policy)
        self.discovery_fallback = discovery_fallback
        if self.discovery_fallback is None and isinstance(self.adapter, Crawl4AIAdapter):
            self.discovery_fallback = RobotsSitemapDiscovery(self.url_policy)
        self.browser_bridge = browser_bridge
        self._browser_batches: dict[str, _BrowserBatchRun] = {}

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

    async def browser_status(self) -> BrowserBridgeStatusResult:
        return await self._browser_bridge().status()

    async def browser_page_read(
        self,
        url: str,
        *,
        purpose: str | None = None,
        timeout_seconds: int = 60,
        request_id: str | None = None,
    ) -> PageReadResult:
        started = time.perf_counter()
        normalized, failure = await self._validate(url)
        if failure is not None:
            return PageReadResult(
                success=False,
                original_url=url,
                request_id=request_id,
                adapter="chrome-extension",
                elapsed_ms=self._elapsed(started),
                failure=failure,
            )
        if timeout_seconds < 15 or timeout_seconds > 120:
            return PageReadResult(
                success=False,
                original_url=normalized,
                request_id=request_id,
                adapter="chrome-extension",
                elapsed_ms=self._elapsed(started),
                failure=FailureDetail(
                    code="invalid_timeout",
                    message="timeout_seconds must be between 15 and 120.",
                    retryable=False,
                ),
            )

        result = await self._browser_bridge().page_read(
            normalized,
            purpose=purpose,
            timeout_seconds=timeout_seconds,
            request_id=request_id,
        )
        if not result.success:
            return result.model_copy(update={"original_url": normalized})
        if not result.final_url:
            return self._browser_result_failure(
                normalized,
                request_id=result.request_id,
                started=started,
                code="invalid_browser_result",
                message="Chrome returned no final URL.",
            )
        try:
            final_url = await self.url_policy.validate(result.final_url)
        except URLPolicyError:
            return self._browser_result_failure(
                normalized,
                request_id=result.request_id,
                started=started,
                code="invalid_browser_result",
                message="Chrome returned a disallowed final URL.",
            )
        if not result.markdown or not verify_page_result_hash(result):
            return self._browser_result_failure(
                normalized,
                request_id=result.request_id,
                started=started,
                code="invalid_browser_result",
                message="Chrome returned empty content or an invalid content hash.",
            )
        return result.model_copy(
            update={
                "original_url": normalized,
                "final_url": final_url,
                "adapter": "chrome-extension",
            }
        )

    async def browser_cancel(self, request_id: str) -> BrowserCancelResult:
        return await self._browser_bridge().cancel(request_id)

    async def browser_batch_start(
        self,
        urls: list[str],
        *,
        purpose: str | None = None,
        timeout_seconds: int = 60,
        run_id: str | None = None,
    ) -> BrowserBatchStatusResult:
        identifier = run_id or uuid.uuid4().hex
        if not _BATCH_ID.fullmatch(identifier):
            return self._batch_failure(
                identifier,
                "invalid_run_id",
                "run_id must contain 1-80 letters, numbers, dot, underscore, or dash characters.",
            )
        if timeout_seconds < 15 or timeout_seconds > 120:
            return self._batch_failure(
                identifier,
                "invalid_timeout",
                "timeout_seconds must be between 15 and 120.",
            )
        if not urls or len(urls) > 20:
            return self._batch_failure(
                identifier,
                "invalid_batch_size",
                "A browser batch must contain between 1 and 20 URLs.",
            )
        normalized_urls: list[str] = []
        seen: set[str] = set()
        for url in urls:
            normalized, failure = await self._validate(url)
            if failure is not None:
                return BrowserBatchStatusResult(
                    success=False,
                    run_id=identifier,
                    state="failed",
                    failure=failure,
                )
            if normalized not in seen:
                seen.add(normalized)
                normalized_urls.append(normalized)

        existing = self._browser_batches.get(identifier)
        if existing is not None:
            if existing.urls != normalized_urls:
                return self._batch_failure(
                    identifier,
                    "run_id_conflict",
                    "run_id is already used for a different URL batch.",
                )
            return self._batch_snapshot(existing)

        bridge_status = await self.browser_status()
        if not bridge_status.success or not bridge_status.connected:
            return self._batch_failure(
                identifier,
                "bridge_offline",
                "Chrome is not connected to the local browser bridge.",
                retryable=True,
            )

        items = [
            BrowserBatchItem(
                index=index,
                url=url,
                request_id=f"{identifier}.{index + 1}",
                state="queued",
            )
            for index, url in enumerate(normalized_urls)
        ]
        run = _BrowserBatchRun(
            run_id=identifier,
            purpose=purpose[:500] if purpose else None,
            timeout_seconds=timeout_seconds,
            urls=normalized_urls,
            items=items,
        )
        self._prune_browser_batches()
        if len(self._browser_batches) >= 50:
            return self._batch_failure(
                identifier,
                "batch_registry_full",
                "Too many browser batches are retained; retry after restarting the plugin.",
                retryable=True,
            )
        self._browser_batches[identifier] = run
        run.task = asyncio.create_task(self._run_browser_batch(run))
        return self._batch_snapshot(run)

    def browser_batch_status(self, run_id: str) -> BrowserBatchStatusResult:
        run = self._browser_batches.get(run_id)
        if run is None:
            return self._batch_failure(
                run_id,
                "batch_not_found",
                "No browser batch exists for the supplied run_id.",
            )
        return self._batch_snapshot(run)

    async def browser_batch_cancel(self, run_id: str) -> BrowserBatchStatusResult:
        run = self._browser_batches.get(run_id)
        if run is None:
            return self._batch_failure(
                run_id,
                "batch_not_found",
                "No browser batch exists for the supplied run_id.",
            )
        if run.state in {"completed", "canceled", "failed"}:
            return self._batch_snapshot(run)
        run.cancel_requested = True
        run.state = "canceled"
        for item in run.items:
            if item.state == "queued":
                item.state = "canceled"
        if run.active_request_id:
            await self.browser_cancel(run.active_request_id)
        return self._batch_snapshot(run)

    async def article_list(
        self,
        url: str,
        *,
        limit: int = 100,
        include_unclassified: bool = True,
    ) -> ArticleListResult:
        if limit < 1 or limit > 500:
            return ArticleListResult(
                success=False,
                original_url=url,
                adapter=self.adapter.name,
                elapsed_ms=0,
                failure=FailureDetail(
                    code="invalid_limit",
                    message="limit must be between 1 and 500.",
                    retryable=False,
                ),
            )
        discovery = await self.site_discover(url)
        if not discovery.success:
            return ArticleListResult(
                success=False,
                original_url=discovery.original_url,
                final_url=discovery.final_url,
                adapter=discovery.adapter,
                elapsed_ms=discovery.elapsed_ms,
                status_code=discovery.status_code,
                failure=discovery.failure,
                capture_warning=discovery.capture_warning,
            )
        candidates = []
        for link in discovery.internal_links:
            if link.inferred_type == "navigation":
                continue
            if not include_unclassified and link.inferred_type != "article":
                continue
            candidates.append(
                ArticleCandidate(
                    url=link.url,
                    title=link.anchor_text,
                    published_at=link.published_at,
                    surrounding_text=link.surrounding_text,
                    inferred_type=link.inferred_type,
                )
            )
        return ArticleListResult(
            success=True,
            original_url=discovery.original_url,
            final_url=discovery.final_url,
            articles=candidates[:limit],
            total_candidates=len(candidates),
            returned_candidates=min(len(candidates), limit),
            adapter=discovery.adapter,
            elapsed_ms=discovery.elapsed_ms,
            status_code=discovery.status_code,
            capture_warning=discovery.capture_warning,
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
            warning = FailureDetail(
                code=exc.code, message=exc.message, retryable=exc.retryable
            )
            if self.discovery_fallback is not None and exc.code in {
                "access_denied",
                "bot_challenge",
                "robots_denied",
            }:
                fallback = await self.discovery_fallback.discover(normalized)
                if fallback is not None:
                    return SiteDiscoveryResult(
                        success=True,
                        original_url=normalized,
                        final_url=fallback.final_url,
                        sitemap_urls=fallback.sitemap_urls,
                        internal_links=fallback.internal_links,
                        adapter=self.discovery_fallback.name,
                        elapsed_ms=self._elapsed(started),
                        status_code=fallback.status_code,
                        capture_warning=warning,
                    )
            return self._discovery_failure(
                normalized,
                started,
                warning,
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

    def _browser_bridge(self) -> BrowserBridge:
        if self.browser_bridge is None:
            self.browser_bridge = default_browser_bridge()
        return self.browser_bridge

    def _browser_result_failure(
        self,
        original_url: str,
        *,
        request_id: str | None,
        started: float,
        code: str,
        message: str,
    ) -> PageReadResult:
        return PageReadResult(
            success=False,
            original_url=original_url,
            request_id=request_id,
            adapter="chrome-extension",
            elapsed_ms=self._elapsed(started),
            failure=FailureDetail(code=code, message=message, retryable=False),
        )

    async def _run_browser_batch(self, run: _BrowserBatchRun) -> None:
        run.state = "running"
        run.started_at = _utc_now()
        try:
            for item in run.items:
                if run.cancel_requested:
                    if item.state == "queued":
                        item.state = "canceled"
                    continue
                item.state = "running"
                run.active_request_id = item.request_id
                result = await self.browser_page_read(
                    item.url,
                    purpose=run.purpose,
                    timeout_seconds=run.timeout_seconds,
                    request_id=item.request_id,
                )
                run.active_request_id = None
                if run.cancel_requested:
                    item.state = "canceled"
                    continue
                item.result = result
                item.state = "succeeded" if result.success else "failed"
            if not run.cancel_requested:
                run.state = "completed"
        except asyncio.CancelledError:
            run.cancel_requested = True
            run.state = "canceled"
            for item in run.items:
                if item.state in {"queued", "running"}:
                    item.state = "canceled"
            raise
        except Exception:
            run.state = "failed"
            run.failure = FailureDetail(
                code="batch_execution_failed",
                message="The browser batch stopped because of an internal execution error.",
                retryable=True,
            )
            for item in run.items:
                if item.state in {"queued", "running"}:
                    item.state = "canceled"
        finally:
            run.active_request_id = None
            run.completed_at = _utc_now()

    @staticmethod
    def _batch_snapshot(run: _BrowserBatchRun) -> BrowserBatchStatusResult:
        return BrowserBatchStatusResult(
            success=True,
            run_id=run.run_id,
            state=run.state,
            total=len(run.items),
            completed=sum(
                item.state in {"succeeded", "failed", "canceled"}
                for item in run.items
            ),
            succeeded=sum(item.state == "succeeded" for item in run.items),
            failed=sum(item.state == "failed" for item in run.items),
            canceled=sum(item.state == "canceled" for item in run.items),
            started_at=run.started_at,
            completed_at=run.completed_at,
            active_request_id=run.active_request_id,
            items=[item.model_copy(deep=True) for item in run.items],
            failure=run.failure,
        )

    @staticmethod
    def _batch_failure(
        run_id: str,
        code: str,
        message: str,
        *,
        retryable: bool = False,
    ) -> BrowserBatchStatusResult:
        return BrowserBatchStatusResult(
            success=False,
            run_id=run_id,
            state="failed",
            failure=FailureDetail(code=code, message=message, retryable=retryable),
        )

    def _prune_browser_batches(self) -> None:
        if len(self._browser_batches) < 50:
            return
        for run_id, run in list(self._browser_batches.items()):
            if run.state in {"completed", "canceled", "failed"}:
                del self._browser_batches[run_id]
            if len(self._browser_batches) < 50:
                break

    @staticmethod
    def _elapsed(started: float) -> int:
        return round((time.perf_counter() - started) * 1000)
