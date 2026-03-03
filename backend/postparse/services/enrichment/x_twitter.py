"""X/Twitter enricher using fxtwitter.com proxy for tweet text extraction.

X.com is a JS-heavy SPA that returns empty HTML to simple HTTP clients.
This enricher rewrites X/Twitter URLs to fxtwitter.com and fetches
the og:description meta tag (which contains the tweet text).

Uses a bot-style User-Agent so fxtwitter returns the meta-tag HTML
instead of redirecting to x.com.

Example:
    ```python
    enricher = XEnricher()
    result = enricher.enrich("", source_url="https://x.com/jack/status/20")
    print(result.generated_text)  # "just setting up my twttr"
    ```
"""

import re
from html.parser import HTMLParser
from typing import Optional
from urllib.parse import urlparse

import httpx

from backend.postparse.services.enrichment.base import BaseEnricher, EnrichmentResult

_X_DOMAINS = {"x.com", "twitter.com", "www.x.com", "www.twitter.com", "mobile.twitter.com"}


def is_x_url(url: str) -> bool:
    """Return True if *url* points to an X / Twitter post.

    Args:
        url: URL string to test.

    Returns:
        True if the domain is an X/Twitter domain.

    Example:
        >>> is_x_url("https://x.com/jack/status/20")
        True
        >>> is_x_url("https://twitter.com/jack/status/20")
        True
        >>> is_x_url("https://github.com")
        False
    """
    try:
        domain = urlparse(url).netloc.lower()
        return domain in _X_DOMAINS
    except Exception:
        return False


class _OgMetaParser(HTMLParser):
    """Minimal parser that extracts og:title, og:description, og:image."""

    def __init__(self) -> None:
        super().__init__()
        self.og_title: Optional[str] = None
        self.og_description: Optional[str] = None
        self.og_image: Optional[str] = None

    def handle_starttag(self, tag: str, attrs: list) -> None:
        if tag != "meta":
            return
        attr_dict = dict(attrs)
        prop = attr_dict.get("property", "").lower()
        content = attr_dict.get("content", "")
        if prop == "og:title":
            self.og_title = content
        elif prop == "og:description":
            self.og_description = content
        elif prop == "og:image":
            self.og_image = content


def _to_fxtwitter_url(url: str) -> str:
    """Rewrite an X/Twitter URL to fxtwitter.com.

    Args:
        url: Original X or Twitter URL.

    Returns:
        Equivalent fxtwitter.com URL.

    Example:
        >>> _to_fxtwitter_url("https://x.com/jack/status/20")
        'https://fxtwitter.com/jack/status/20'
    """
    parsed = urlparse(url)
    return parsed._replace(netloc="fxtwitter.com", scheme="https").geturl()


class XEnricher(BaseEnricher):
    """Enricher for X/Twitter URLs via fxtwitter proxy.

    Fetches tweet text by rewriting the URL to fxtwitter.com and
    parsing og:description from the response HTML. Uses a bot
    User-Agent so fxtwitter serves meta tags instead of redirecting.

    Attributes:
        timeout: HTTP request timeout in seconds.

    Example:
        ```python
        enricher = XEnricher()
        result = enricher.enrich("", "https://x.com/jack/status/20")
        print(result.metadata["author"])  # "jack (@jack)"
        print(result.metadata["tweet_text"])  # "just setting up my twttr"
        ```
    """

    ENRICHER_NAME = "x_enricher"

    def __init__(self, timeout: float = 10.0) -> None:
        """Initialize the enricher.

        Args:
            timeout: HTTP request timeout in seconds (default 10).
        """
        self.timeout = timeout
        self.headers = {
            "User-Agent": "Twitterbot/1.0",
            "Accept": "text/html,application/xhtml+xml,*/*;q=0.8",
        }

    def enrich(
        self,
        content: str,
        source_url: Optional[str] = None,
    ) -> EnrichmentResult:
        """Fetch tweet text from an X/Twitter URL.

        Args:
            content: Original message content (not used).
            source_url: X or Twitter URL to enrich.

        Returns:
            EnrichmentResult with tweet text as generated_text.

        Raises:
            ValueError: If source_url is missing or not an X URL.
            RuntimeError: If fxtwitter returns an error or the post
                doesn't exist.

        Example:
            ```python
            result = XEnricher().enrich("", "https://x.com/jack/status/20")
            print(result.generated_text)
            ```
        """
        if not source_url:
            raise ValueError("source_url is required for XEnricher")
        if not is_x_url(source_url):
            raise ValueError(f"Not an X/Twitter URL: {source_url}")

        fx_url = _to_fxtwitter_url(source_url)
        response = httpx.get(
            fx_url,
            timeout=self.timeout,
            headers=self.headers,
            follow_redirects=False,
        )
        response.raise_for_status()

        parser = _OgMetaParser()
        parser.feed(response.text)

        author = parser.og_title or ""
        tweet_text = parser.og_description or ""

        if not tweet_text or "doesn't exist" in tweet_text.lower():
            raise RuntimeError(f"Tweet not found or unavailable: {source_url}")

        parts = []
        if author:
            parts.append(f"Author: {author}")
        parts.append(f"Tweet: {tweet_text}")

        return EnrichmentResult(
            enrichment_type="description",
            enricher_name=self.ENRICHER_NAME,
            generated_text="\n".join(parts),
            source_url=source_url,
            metadata={
                "author": author,
                "tweet_text": tweet_text,
                "image_url": parser.og_image,
            },
        )
