"""Provider-neutral web capture and Markdown archive tools for AI agents."""

from agentictools.models import (
    ArticleCandidate,
    ArticleListResult,
    ArchiveSearchResult,
    BrowserBatchItem,
    BrowserBatchStatusResult,
    BrowserBridgeStatusResult,
    BrowserCancelResult,
    PageReadResult,
    PageSaveResult,
    SiteDiscoveryResult,
)
from agentictools.service import AgentWebArchiveService

__all__ = [
    "AgentWebArchiveService",
    "ArticleCandidate",
    "ArticleListResult",
    "ArchiveSearchResult",
    "BrowserBatchItem",
    "BrowserBatchStatusResult",
    "BrowserBridgeStatusResult",
    "BrowserCancelResult",
    "PageReadResult",
    "PageSaveResult",
    "SiteDiscoveryResult",
]
