"""Read-only, provider-neutral web capture tools for AI agents."""

from agentictools.models import PageReadResult, SiteDiscoveryResult
from agentictools.service import AgentWebArchiveService

__all__ = ["AgentWebArchiveService", "PageReadResult", "SiteDiscoveryResult"]
