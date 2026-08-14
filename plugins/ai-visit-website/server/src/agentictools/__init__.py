"""Provider-neutral web capture and Markdown archive tools for AI agents."""

from agentictools.models import (
    ArchiveSearchResult,
    PageReadResult,
    PageSaveResult,
    SiteDiscoveryResult,
)
from agentictools.service import AgentWebArchiveService

__all__ = [
    "AgentWebArchiveService",
    "ArchiveSearchResult",
    "PageReadResult",
    "PageSaveResult",
    "SiteDiscoveryResult",
]
