from __future__ import annotations

from pydantic import BaseModel, Field


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
