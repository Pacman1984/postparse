"""Instagram links are never scraped by the enrichment stack.

Instagram content is only collected by the logged-in, throttled Instagram
collector; anonymous page requests would add block risk for nothing (the
pages need a login). Links are recorded as ``skipped`` without any request.
"""

from __future__ import annotations

import httpx

from postparse.core.db.models import Link
from postparse.enrichment.fetchers.base import FetchResult

__all__ = ["INSTAGRAM_DOMAINS", "InstagramFetcher"]

INSTAGRAM_DOMAINS = frozenset({"instagram.com", "instagr.am", "ig.me", "cdninstagram.com"})

SKIP_REASON = "Instagram links are only collected by the Instagram collector"


class InstagramFetcher:
    """Marks Instagram links ``skipped`` (no network)."""

    name = "instagram"
    uses_network = False

    def matches(self, link: Link) -> bool:
        """Instagram domains."""
        return link.domain in INSTAGRAM_DOMAINS

    async def fetch(self, link: Link, client: httpx.AsyncClient) -> FetchResult:
        """Return a ``skipped`` result without any request."""
        result = FetchResult.skip(SKIP_REASON)
        result.fetcher = self.name
        return result
