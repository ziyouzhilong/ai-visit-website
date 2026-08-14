from __future__ import annotations

import time
from collections.abc import Mapping

from crawl4ai import AsyncWebCrawler, BrowserConfig, CacheMode, CrawlerRunConfig

from agentictools.adapters.base import AdapterFailure, CaptureDocument
from agentictools.url_policy import PublicURLPolicy, URLPolicyError


class Crawl4AIAdapter:
    """Render a public page and convert it to Markdown without model calls."""

    name = "crawl4ai"

    def __init__(self, url_policy: PublicURLPolicy | None = None) -> None:
        self.url_policy = url_policy or PublicURLPolicy()

    async def read(self, url: str) -> CaptureDocument:
        started = time.perf_counter()
        browser_config = self._browser_config()
        run_config = self._run_config()

        try:
            crawler = AsyncWebCrawler(config=browser_config)
            crawler.crawler_strategy.set_hook(
                "on_page_context_created", self._install_request_policy
            )
            async with crawler:
                result = await crawler.arun(url=url, config=run_config)
        except Exception as exc:
            raise AdapterFailure(
                code="connection_failed",
                message="The page could not be reached by the browser adapter.",
                retryable=True,
            ) from exc

        elapsed_ms = round((time.perf_counter() - started) * 1000)
        status_code = result.status_code
        if not result.success:
            code, message, retryable = self._classify_failure(status_code, result.error_message)
            raise AdapterFailure(
                code=code,
                message=message,
                retryable=retryable,
                status_code=status_code,
            )

        metadata = result.metadata if isinstance(result.metadata, Mapping) else {}
        markdown_result = result.markdown
        markdown = markdown_result.raw_markdown if markdown_result else ""
        final_url = result.redirected_url or result.url or url
        return CaptureDocument(
            requested_url=url,
            final_url=final_url,
            title=self._first(metadata, "title", "og:title"),
            markdown=markdown or "",
            html=result.html or result.cleaned_html or "",
            status_code=status_code,
            published_at=self._first(
                metadata,
                "published_time",
                "article:published_time",
                "date",
                "datePublished",
            ),
            author=self._first(metadata, "author", "article:author", "byline"),
            elapsed_ms=elapsed_ms,
            adapter=self.name,
        )

    @staticmethod
    def _run_config() -> CrawlerRunConfig:
        return CrawlerRunConfig(
            cache_mode=CacheMode.BYPASS,
            excluded_tags=[
                "nav",
                "footer",
                "header",
                "form",
                "aside",
                "button",
                "dialog",
                "script",
                "style",
                "noscript",
            ],
            remove_forms=True,
            wait_until="domcontentloaded",
            page_timeout=45_000,
            check_robots_txt=True,
            verbose=False,
        )

    @staticmethod
    def _browser_config() -> BrowserConfig:
        return BrowserConfig(
            headless=True,
            verbose=False,
            accept_downloads=False,
        )

    async def _install_request_policy(self, page: object, **_kwargs: object) -> object:
        await page.route("**/*", self._route_handler)  # type: ignore[attr-defined]
        return page

    async def _route_handler(self, route: object) -> None:
        request_url = route.request.url  # type: ignore[attr-defined]
        if not request_url.lower().startswith(("http://", "https://")):
            await route.continue_()  # type: ignore[attr-defined]
            return
        try:
            await self.url_policy.validate(request_url)
        except URLPolicyError:
            await route.abort("blockedbyclient")  # type: ignore[attr-defined]
            return
        await route.continue_()  # type: ignore[attr-defined]

    @staticmethod
    def _first(metadata: Mapping[object, object], *keys: str) -> str | None:
        for key in keys:
            value = metadata.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
        return None

    @staticmethod
    def _classify_failure(
        status_code: int | None, error_message: str | None
    ) -> tuple[str, str, bool]:
        if status_code in {401, 403}:
            return "access_denied", f"The origin returned HTTP {status_code}.", False
        if status_code == 404:
            return "not_found", "The origin returned HTTP 404.", False
        if status_code == 429:
            return "rate_limited", "The origin returned HTTP 429.", True
        if status_code is not None and status_code >= 500:
            return "upstream_error", f"The origin returned HTTP {status_code}.", True
        lowered = (error_message or "").lower()
        if "robot" in lowered:
            return "robots_denied", "The site's robots policy denied capture.", False
        if "anti-bot" in lowered or "captcha" in lowered:
            return "bot_challenge", "The site presented an automated-access challenge.", False
        return "capture_failed", "The browser adapter could not capture the page.", True
