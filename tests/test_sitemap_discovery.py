from __future__ import annotations

import pytest

from agentictools.sitemap_discovery import RobotsSitemapDiscovery


class AllowExamplePolicy:
    async def validate(self, url: str) -> str:
        return url


class FixtureDiscovery(RobotsSitemapDiscovery):
    def __init__(self, fixtures: dict[str, bytes]) -> None:
        super().__init__(AllowExamplePolicy(), max_sitemap_documents=4, max_links=10)
        self.fixtures = fixtures
        self.fetch_count = 0

    async def _fetch(self, url: str) -> tuple[int, str, bytes] | None:
        self.fetch_count += 1
        body = self.fixtures.get(url)
        return None if body is None else (200, url, body)


@pytest.mark.asyncio
async def test_discovers_titled_articles_from_robots_news_sitemap() -> None:
    robots = b"Sitemap: https://example.com/news-index.xml\n"
    index = b"""<?xml version="1.0"?>
    <sitemapindex xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
      <sitemap><loc>https://example.com/news.xml</loc></sitemap>
    </sitemapindex>
    """
    news = b"""<?xml version="1.0"?>
    <urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9"
            xmlns:news="http://www.google.com/schemas/sitemap-news/0.9">
      <url>
        <loc>https://example.com/business/report</loc>
        <lastmod>2026-08-15T00:01:00Z</lastmod>
        <news:news>
          <news:publication_date>2026-08-15T00:00:00Z</news:publication_date>
          <news:title>Business report</news:title>
        </news:news>
      </url>
      <url>
        <loc>https://example.com/technology/other</loc>
        <news:news><news:title>Technology report</news:title></news:news>
      </url>
      <url><loc>https://outside.example/story</loc></url>
    </urlset>
    """
    discovery = FixtureDiscovery(
        {
            "https://example.com/robots.txt": robots,
            "https://example.com/news-index.xml": index,
            "https://example.com/news.xml": news,
        }
    )

    result = await discovery.discover("https://example.com/business/")

    assert result is not None
    assert [item.url for item in result.internal_links] == [
        "https://example.com/business/report"
    ]
    assert result.internal_links[0].anchor_text == "Business report"
    assert result.internal_links[0].published_at == "2026-08-15T00:00:00Z"
    assert "2026-08-15T00:00:00Z" in result.internal_links[0].surrounding_text

    first_fetch_count = discovery.fetch_count
    technology = await discovery.discover("https://example.com/technology/")

    assert technology is not None
    assert [item.anchor_text for item in technology.internal_links] == [
        "Technology report"
    ]
    assert discovery.fetch_count == first_fetch_count
