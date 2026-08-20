from __future__ import annotations

from pydantic import BaseModel, Field, field_validator


class FailureDetail(BaseModel):
    """A stable, sanitized failure returned to an agent."""

    code: str = Field(description="Stable machine-readable failure code.")
    message: str = Field(description="Sanitized explanation without credentials or headers.")
    retryable: bool = Field(description="Whether retrying later may reasonably succeed.")


class LinkEvidence(BaseModel):
    """A link and the page evidence that exposed it."""

    url: str
    anchor_text: str
    surrounding_text: str = ""
    published_at: str | None = None
    inferred_type: str = Field(
        default="link",
        description="Structural hint such as navigation, article, section, feed, or sitemap.",
    )


class ArticleCandidate(BaseModel):
    """One discovery candidate for the calling agent to evaluate."""

    url: str
    title: str
    published_at: str | None = None
    surrounding_text: str = ""
    inferred_type: str = "link"


class ArticleListResult(BaseModel):
    """Bounded article/link candidates derived from site discovery evidence."""

    success: bool
    original_url: str
    final_url: str | None = None
    articles: list[ArticleCandidate] = Field(default_factory=list)
    total_candidates: int = Field(default=0, ge=0)
    returned_candidates: int = Field(default=0, ge=0)
    adapter: str
    elapsed_ms: int
    status_code: int | None = None
    failure: FailureDetail | None = None
    capture_warning: FailureDetail | None = None


class PageReadResult(BaseModel):
    """Structured output for one read-only page capture."""

    success: bool
    original_url: str
    request_id: str | None = None
    final_url: str | None = None
    title: str | None = None
    published_at: str | None = None
    author: str | None = None
    markdown: str | None = None
    content_hash: str | None = None
    adapter: str
    elapsed_ms: int
    status_code: int | None = None
    paragraph_count: int | None = Field(default=None, ge=0)
    article_text_length: int | None = Field(default=None, ge=0)
    selector_strategy: str | None = None
    failure: FailureDetail | None = None


class BrowserBridgeStatusResult(BaseModel):
    """Current state of the authenticated local Chrome bridge."""

    success: bool
    configured: bool
    connected: bool
    endpoint: str | None = None
    extension_version: str | None = None
    last_seen_at: str | None = None
    queued_tasks: int = Field(default=0, ge=0)
    active_request_id: str | None = None
    failure: FailureDetail | None = None


class BrowserCancelResult(BaseModel):
    """Outcome of canceling a queued or running browser request."""

    success: bool
    request_id: str
    status: str = Field(description="canceled, not_found, already_finished, or failed")
    failure: FailureDetail | None = None


class BrowserBatchItem(BaseModel):
    """Progress and optional read result for one URL in a browser batch."""

    index: int = Field(ge=0)
    url: str
    request_id: str
    state: str = Field(description="queued, running, succeeded, failed, or canceled")
    result: PageReadResult | None = None


class BrowserBatchStatusResult(BaseModel):
    """Current state of one bounded, sequential Chrome reading batch."""

    success: bool
    run_id: str
    state: str = Field(description="queued, running, completed, canceled, or failed")
    total: int = Field(default=0, ge=0)
    completed: int = Field(default=0, ge=0)
    succeeded: int = Field(default=0, ge=0)
    failed: int = Field(default=0, ge=0)
    canceled: int = Field(default=0, ge=0)
    started_at: str | None = None
    completed_at: str | None = None
    active_request_id: str | None = None
    items: list[BrowserBatchItem] = Field(default_factory=list)
    failure: FailureDetail | None = None


class SiteDiscoveryResult(BaseModel):
    """Structural evidence from a site entry point for an agent to evaluate."""

    success: bool
    original_url: str
    final_url: str | None = None
    title: str | None = None
    navigation: list[LinkEvidence] = Field(default_factory=list)
    feed_urls: list[str] = Field(default_factory=list)
    sitemap_urls: list[str] = Field(default_factory=list)
    internal_links: list[LinkEvidence] = Field(default_factory=list)
    adapter: str
    elapsed_ms: int
    status_code: int | None = None
    failure: FailureDetail | None = None
    capture_warning: FailureDetail | None = Field(
        default=None,
        description="Original page-capture failure when public sitemap fallback succeeded.",
    )


class PageSaveRequest(BaseModel):
    """An agent-approved page payload to persist without another network read."""

    source_url: str
    title: str = Field(min_length=1, max_length=500)
    markdown: str = Field(min_length=1)
    published_at: str | None = None
    author: str | None = Field(default=None, max_length=500)
    tags: list[str] = Field(default_factory=list, max_length=100)
    task_id: str | None = Field(default=None, max_length=200)
    expected_content_hash: str | None = Field(
        default=None,
        pattern=r"^sha256:[0-9a-f]{64}$",
        description="Optional hash returned by page_read; reject the save if content changed.",
    )

    @field_validator("title")
    @classmethod
    def title_must_not_be_blank(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("title must not be blank")
        return stripped


class PageSaveResult(BaseModel):
    """Outcome of one idempotent archive write."""

    success: bool
    status: str = Field(description="saved, duplicate, or failed")
    document_id: str | None = None
    resource_uri: str | None = None
    source_url: str | None = None
    title: str | None = None
    captured_at: str | None = None
    content_hash: str | None = None
    tags: list[str] = Field(default_factory=list)
    failure: FailureDetail | None = None


class ArchiveSearchMatch(BaseModel):
    """Concise metadata and a resource URI for one archived document."""

    document_id: str
    resource_uri: str
    title: str
    source_url: str
    published_at: str | None = None
    captured_at: str
    tags: list[str] = Field(default_factory=list)
    content_hash: str
    excerpt: str


class ArchiveSearchResult(BaseModel):
    """Filtered archive matches ordered newest-first."""

    success: bool
    total: int = 0
    matches: list[ArchiveSearchMatch] = Field(default_factory=list)
    failure: FailureDetail | None = None
