"""YouTube enricher using the YouTube oEmbed API and page meta tags.

Fetches title and description for YouTube URLs without requiring an API key.

- Title: from oEmbed API (reliable, fast)
- Description: from og:description meta tag on the watch page

Example:
    ```python
    enricher = YouTubeEnricher()
    result = enricher.enrich("", source_url="https://youtube.com/watch?v=abc")
    print(result.generated_text)  # "Title: ...\\nDescription: ..."
    ```
"""

import re
from html.parser import HTMLParser
from typing import Any, Dict, Optional
from urllib.parse import quote_plus

import httpx

from backend.postparse.services.enrichment.base import BaseEnricher, EnrichmentResult

_OEMBED_URL = "https://www.youtube.com/oembed?url={url}&format=json"
_YOUTUBE_DOMAINS = {"youtube.com", "youtu.be", "www.youtube.com", "m.youtube.com"}


def is_youtube_url(url: str) -> bool:
    """Return True if url is a YouTube link.

    Args:
        url: URL string to test.

    Returns:
        True if the domain is a YouTube domain.

    Example:
        >>> is_youtube_url("https://youtu.be/abc")
        True
        >>> is_youtube_url("https://github.com")
        False
    """
    try:
        from urllib.parse import urlparse
        domain = urlparse(url).netloc.lower().lstrip("www.")
        return domain in _YOUTUBE_DOMAINS or domain.endswith(".youtube.com")
    except Exception:
        return False


class _MetaTagParser(HTMLParser):
    """Minimal HTML parser that extracts <meta> og:description / description.

    Also extracts the page <title> tag as a fallback.
    """

    def __init__(self) -> None:
        super().__init__()
        self.og_description: Optional[str] = None
        self.meta_description: Optional[str] = None
        self._in_title = False
        self.title: Optional[str] = None

    def handle_starttag(self, tag: str, attrs: list) -> None:
        if tag == "meta":
            attr_dict = dict(attrs)
            prop = attr_dict.get("property", "").lower()
            name = attr_dict.get("name", "").lower()
            content = attr_dict.get("content", "")
            if prop == "og:description":
                self.og_description = content
            elif name == "description":
                self.meta_description = content
        elif tag == "title":
            self._in_title = True

    def handle_data(self, data: str) -> None:
        if self._in_title and self.title is None:
            self.title = data.strip()

    def handle_endtag(self, tag: str) -> None:
        if tag == "title":
            self._in_title = False


class YouTubeEnricher(BaseEnricher):
    """Enricher for YouTube URLs: fetches title and description.

    Uses:
    1. oEmbed API for title (fast, no auth required)
    2. og:description meta tag from the watch page for description

    Attributes:
        timeout: HTTP request timeout in seconds.
        headers: HTTP headers sent with every request.

    Example:
        ```python
        enricher = YouTubeEnricher()
        result = enricher.enrich("", "https://youtu.be/dQw4w9WgXcQ")
        print(result.metadata["title"])
        print(result.metadata["author"])
        ```
    """

    ENRICHER_NAME = "youtube_enricher"

    def __init__(self, timeout: float = 10.0) -> None:
        """Initialize the enricher.

        Args:
            timeout: HTTP request timeout in seconds (default 10).
        """
        self.timeout = timeout
        self.headers = {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/131.0.0.0 Safari/537.36"
            ),
            "Accept-Language": "en-US,en;q=0.9",
        }

    def _fetch_oembed(self, url: str) -> Dict[str, Any]:
        """Fetch oEmbed metadata for a YouTube URL.

        Args:
            url: YouTube URL.

        Returns:
            oEmbed response dict with at least 'title' and 'author_name'.

        Raises:
            httpx.HTTPError: On request failure.
        """
        oembed_url = _OEMBED_URL.format(url=quote_plus(url))
        response = httpx.get(oembed_url, timeout=self.timeout, headers=self.headers)
        response.raise_for_status()
        return response.json()

    def _fetch_description(self, url: str) -> Optional[str]:
        """Fetch og:description from the YouTube watch page.

        Args:
            url: YouTube URL.

        Returns:
            Description string, or None if not found.
        """
        try:
            response = httpx.get(
                url, timeout=self.timeout, headers=self.headers, follow_redirects=True
            )
            response.raise_for_status()
            parser = _MetaTagParser()
            parser.feed(response.text[:50_000])  # only parse head section
            return parser.og_description or parser.meta_description
        except Exception:
            return None

    def enrich(
        self,
        content: str,
        source_url: Optional[str] = None,
    ) -> EnrichmentResult:
        """Fetch YouTube title and description.

        Args:
            content: Original message content (used as context only).
            source_url: YouTube URL to enrich.

        Returns:
            EnrichmentResult with title and description as generated_text.

        Raises:
            ValueError: If source_url is not a YouTube URL or is missing.

        Example:
            ```python
            result = YouTubeEnricher().enrich(
                "", "https://youtube.com/watch?v=dQw4w9WgXcQ"
            )
            print(result.generated_text)
            ```
        """
        if not source_url:
            raise ValueError("source_url is required for YouTubeEnricher")
        if not is_youtube_url(source_url):
            raise ValueError(f"Not a YouTube URL: {source_url}")

        oembed = self._fetch_oembed(source_url)
        title = oembed.get("title", "")
        author = oembed.get("author_name", "")
        description = self._fetch_description(source_url)

        parts = []
        if title:
            parts.append(f"Title: {title}")
        if author:
            parts.append(f"Channel: {author}")
        if description:
            parts.append(f"Description: {description}")

        generated_text = "\n".join(parts) if parts else title or source_url

        return EnrichmentResult(
            enrichment_type="description",
            enricher_name=self.ENRICHER_NAME,
            generated_text=generated_text,
            source_url=source_url,
            metadata={
                "title": title,
                "author": author,
                "description": description,
                "thumbnail_url": oembed.get("thumbnail_url"),
            },
        )
