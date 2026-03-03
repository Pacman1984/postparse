"""Content enrichment services.

This package provides enrichers that fetch additional information
for URLs stored in content_expanded.

Available enrichers:
- YouTubeEnricher: Fetches YouTube title and description via oEmbed API
- LinkScraper: Fetches title, description, and cleaned body for any URL

Example:
    ```python
    from backend.postparse.services.enrichment import YouTubeEnricher, LinkScraper

    yt = YouTubeEnricher()
    result = yt.enrich("", source_url="https://youtube.com/watch?v=abc")
    print(result.metadata["title"])

    scraper = LinkScraper()
    result = scraper.enrich("", source_url="https://arxiv.org/abs/2401.00001")
    print(result.metadata["title"])
    ```
"""

from backend.postparse.services.enrichment.base import BaseEnricher, EnrichmentResult
from backend.postparse.services.enrichment.youtube import YouTubeEnricher, is_youtube_url
from backend.postparse.services.enrichment.link_scraper import LinkScraper

__all__ = [
    "BaseEnricher",
    "EnrichmentResult",
    "YouTubeEnricher",
    "is_youtube_url",
    "LinkScraper",
]
