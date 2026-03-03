"""General link scraper enricher using httpx and lxml.

Fetches title, description, and cleaned body text for arbitrary web URLs.
Uses lxml for robust HTML parsing and cleanup.

Example:
    ```python
    scraper = LinkScraper()
    result = scraper.enrich("", source_url="https://arxiv.org/abs/2401.00001")
    print(result.metadata["title"])
    print(result.generated_text)  # title + description + body
    ```
"""

import re
from typing import List, Optional, Tuple

import httpx
from lxml import html as lxml_html

from backend.postparse.services.enrichment.base import BaseEnricher, EnrichmentResult

# Tags whose content we remove before extracting body text (relative to body)
_SKIP_XPATH = (
    ".//script | .//style | .//noscript | .//nav | .//footer | .//header | "
    ".//aside | .//form | .//button | .//iframe | .//svg | .//canvas"
)


def _extract_meta(tree: lxml_html.HtmlElement) -> Tuple[str, str]:
    """Extract title and description from meta tags and <title>.

    Args:
        tree: Parsed lxml HTML tree.

    Returns:
        Tuple of (title, description).
    """
    title = ""
    description = ""

    for meta in tree.xpath("//meta"):
        prop = (meta.get("property") or "").lower()
        name = (meta.get("name") or "").lower()
        content = meta.get("content") or ""
        if prop == "og:title":
            title = content
        elif prop == "og:description":
            description = content
        elif name == "description":
            description = description or content

    if not title:
        title_elem = tree.find(".//title")
        if title_elem is not None and title_elem.text:
            title = title_elem.text.strip()

    return title, description


def _extract_body_text(tree: lxml_html.HtmlElement, max_chars: int = 5000) -> str:
    """Extract cleaned body text, removing scripts/nav/footer etc.

    Args:
        tree: Parsed lxml HTML tree.
        max_chars: Maximum characters to return.

    Returns:
        Cleaned, whitespace-normalised body text.
    """
    body = tree.find(".//body")
    if body is None:
        return ""

    # Remove unwanted elements (modifies tree in place)
    for elem in body.xpath(_SKIP_XPATH):
        parent = elem.getparent()
        if parent is not None:
            parent.remove(elem)

    raw = body.text_content() or ""
    clean = re.sub(r"\n{3,}", "\n\n", re.sub(r" {2,}", " ", raw))
    return clean[:max_chars].strip()


class LinkScraper(BaseEnricher):
    """General-purpose web link enricher.

    Fetches a URL and extracts:
    - Page title (og:title or <title>)
    - Description (og:description or meta description)
    - Cleaned body text (visible text, no scripts/nav/footer)

    Uses httpx for fetching and lxml for HTML parsing and cleanup.

    Attributes:
        timeout: HTTP request timeout in seconds.
        max_body_chars: Maximum body text characters to store.
        headers: HTTP headers sent with every request.

    Example:
        ```python
        scraper = LinkScraper()
        result = scraper.enrich("", "https://arxiv.org/abs/2401.00001")
        print(result.metadata["title"])
        print(result.generated_text[:200])
        ```
    """

    ENRICHER_NAME = "link_scraper"

    def __init__(
        self,
        timeout: float = 15.0,
        max_body_chars: int = 5000,
    ) -> None:
        """Initialize the link scraper.

        Args:
            timeout: HTTP request timeout in seconds (default 15).
            max_body_chars: Max body text chars to store (default 5000).
        """
        self.timeout = timeout
        self.max_body_chars = max_body_chars
        self.headers = {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/131.0.0.0 Safari/537.36"
            ),
            "Accept": "text/html,application/xhtml+xml,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9",
        }

    def _fetch_page(self, url: str) -> Tuple[str, str]:
        """Fetch URL and return (html_text, final_url_after_redirects).

        Args:
            url: URL to fetch.

        Returns:
            Tuple of (response_text, final_url).

        Raises:
            httpx.HTTPError: On HTTP-level error.
        """
        response = httpx.get(
            url,
            timeout=self.timeout,
            headers=self.headers,
            follow_redirects=True,
        )
        response.raise_for_status()
        return response.text, str(response.url)

    def enrich(
        self,
        content: str,
        source_url: Optional[str] = None,
    ) -> EnrichmentResult:
        """Fetch and parse a web URL.

        Args:
            content: Original message content (not used for fetching).
            source_url: URL to scrape.

        Returns:
            EnrichmentResult with title, description, and body as
            generated_text; metadata dict with individual fields.

        Raises:
            ValueError: If source_url is missing.

        Example:
            ```python
            result = LinkScraper().enrich("", "https://arxiv.org/abs/2401.00001")
            print(result.metadata["title"])
            print(result.metadata["description"])
            ```
        """
        if not source_url:
            raise ValueError("source_url is required for LinkScraper")

        html_text, final_url = self._fetch_page(source_url)
        tree = lxml_html.fromstring(html_text)

        title, description = _extract_meta(tree)
        body = _extract_body_text(tree, max_chars=self.max_body_chars)

        parts: List[str] = []
        if title:
            parts.append(f"Title: {title}")
        if description:
            parts.append(f"Description: {description}")
        if body:
            parts.append(f"Body:\n{body}")

        generated_text = "\n\n".join(parts) if parts else source_url

        return EnrichmentResult(
            enrichment_type="description",
            enricher_name=self.ENRICHER_NAME,
            generated_text=generated_text,
            source_url=final_url,
            metadata={
                "title": title,
                "description": description,
                "body_chars": len(body),
            },
        )
