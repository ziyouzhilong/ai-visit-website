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
    inferred_type: str = Field(
        default="link",
        description="Structural hint such as navigation, article, section, feed, or sitemap.",
    )


class PageReadResult(BaseModel):
    """Structured output for one read-only page capture."""

    success: bool
    original_url: str
    final_url: str | None = None
    title: str | None = None
    published_at: str | None = None
    author: str | None = None
    markdown: str | None = None
    content_hash: str | None = None
    adapter: str
    elapsed_ms: int
    status_code: int | None = None
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
