"""Generic web pages: httpx + trafilatura, readability-lxml as fallback.

The page is fetched with redirects followed and a body cap (``max_body_mb``;
``max_document_mb`` once the headers announce a document). HTML is extracted
with trafilatura (markdown-ish text with tables, plus title / author / date /
site name / description). When trafilatura finds no main text or less than
``min_text_chars``, readability-lxml is tried as well and the longer text wins.

Other content types:

* PDF / Office documents -> :func:`~postparse.enrichment.fetchers.documents.convert_document`
  (stored with fetcher ``document``);
* ``text/plain`` / ``text/markdown`` -> stored as-is;
* anything else (images, video, JSON, ...) -> ``skipped``.
"""

from __future__ import annotations

import asyncio
import logging
import re
from typing import Any

import httpx

from postparse.core.db.models import Link
from postparse.enrichment.fetchers.base import (
    BodyTooLarge,
    CappedResponse,
    FetchResult,
    charset_of,
    decode_body,
    get_capped,
    http_error,
)
from postparse.enrichment.fetchers.documents import (
    DOCUMENT_TYPES,
    GENERIC_TYPES,
    convert_document,
    document_extension,
)
from postparse.enrichment.options import EnrichmentOptions

__all__ = ["GenericFetcher", "extract_html", "extract_response"]

logger = logging.getLogger(__name__)

_HTML_TYPES = frozenset({"text/html", "application/xhtml+xml", ""})
_TEXT_TYPES = frozenset({"text/plain", "text/markdown", "text/x-markdown"})
_BLANK_LINES = re.compile(r"\n{3,}")
_SPACES = re.compile(r"[ \t\r\f\v]+")


def _clean(text: str | None) -> str:
    if not text:
        return ""
    lines = [_SPACES.sub(" ", line).strip() for line in text.splitlines()]
    return _BLANK_LINES.sub("\n\n", "\n".join(lines)).strip()


def _trafilatura(html: str, url: str) -> tuple[str, dict[str, Any]]:
    import trafilatura

    text = trafilatura.extract(
        html,
        url=url,
        output_format="markdown",
        include_tables=True,
        include_comments=False,
        include_links=False,
        include_images=False,
        favor_recall=True,
        deduplicate=True,
    )
    meta: dict[str, Any] = {}
    document = trafilatura.extract_metadata(html, default_url=url)
    if document is not None:
        for key in (
            "title",
            "author",
            "date",
            "sitename",
            "description",
            "hostname",
            "image",
            "language",
        ):
            value = getattr(document, key, None)
            if value:
                meta[key] = value
        for key in ("categories", "tags"):
            value = getattr(document, key, None)
            if value:
                meta[key] = list(value)
    return _clean(text), meta


def _readability(html: str) -> tuple[str, str | None]:
    from lxml import html as lxml_html
    from readability import Document

    document = Document(html)
    summary = document.summary(html_partial=True)
    tree = lxml_html.fromstring(summary) if summary.strip() else None
    text = ""
    if tree is not None:
        blocks = [
            element.text_content()
            for element in tree.iter("p", "li", "h1", "h2", "h3", "h4", "pre", "blockquote", "td")
        ]
        text = "\n\n".join(_clean(block) for block in blocks if block and block.strip())
        if not text:
            text = _clean(tree.text_content())
    title = document.short_title() or None
    return text, title


def extract_html(html: str, url: str, *, min_text_chars: int = 200) -> FetchResult:
    """Extract text and metadata from an HTML page.

    Args:
        html: Decoded HTML.
        url: Final URL (used for metadata and relative links).
        min_text_chars: Below this length readability is tried as well.

    Returns:
        ``ok`` with title/text (metadata ``extractor`` names the winner) or
        ``skipped`` when the page has neither text nor title.
    """
    text, meta = "", {}
    try:
        text, meta = _trafilatura(html, url)
        extractor = "trafilatura"
    except Exception:  # trafilatura can choke on broken markup
        logger.debug("trafilatura failed for %s", url, exc_info=True)
        extractor = "none"
    title = meta.pop("title", None)
    if len(text) < min_text_chars:
        try:
            fallback, fallback_title = _readability(html)
        except Exception:
            logger.debug("readability failed for %s", url, exc_info=True)
            fallback, fallback_title = "", None
        if len(fallback) > len(text):
            text, extractor = fallback, "readability"
        title = title or fallback_title
    meta["extractor"] = extractor
    if not text and not title:
        return FetchResult.skip("no extractable content", **meta)
    return FetchResult("ok", title=title, text=text or None, metadata=meta)


async def extract_response(response: CappedResponse, options: EnrichmentOptions) -> FetchResult:
    """Turn a fetched response into a result (HTML, plain text or document)."""
    if response.status_code >= 400:
        result = http_error(response.status_code)
        result.fetcher = GenericFetcher.name
        return result
    content_type = response.content_type
    base_meta: dict[str, Any] = {"final_url": response.url, "content_type": content_type or None}
    if response.redirects:
        base_meta["redirects"] = response.redirects
    extension = document_extension(content_type, response.url)
    if extension is not None:
        return await convert_document(
            response.content,
            extension=extension,
            url=response.url,
            content_type=content_type,
            http_status=response.status_code,
            redirects=response.redirects,
        )
    if content_type in _TEXT_TYPES:
        text = _clean(decode_body(response.content, charset_of(response.headers)))
        result = (
            FetchResult("ok", text=text, metadata={**base_meta, "extractor": "plain"})
            if text
            else FetchResult.skip("empty text response", **base_meta)
        )
    elif content_type in _HTML_TYPES:
        html = decode_body(response.content, charset_of(response.headers))
        result = await asyncio.to_thread(
            extract_html, html, response.url, min_text_chars=options.min_text_chars
        )
        result.metadata = {**base_meta, **result.metadata}
    else:
        result = FetchResult.skip(f"unsupported content type {content_type!r}", **base_meta)
    result.http_status = response.status_code
    result.fetcher = GenericFetcher.name
    return result


class GenericFetcher:
    """Fallback fetcher for any http(s) page.

    Args:
        options: Caps and extraction thresholds.
    """

    name = "generic"
    uses_network = True

    def __init__(self, options: EnrichmentOptions | None = None) -> None:
        self.options = options or EnrichmentOptions()

    def matches(self, link: Link) -> bool:
        """Matches every link (the router uses it as the default)."""
        return True

    def _cap(self, content_type: str) -> int:
        if content_type in _HTML_TYPES or content_type in _TEXT_TYPES:
            return self.options.max_body_bytes
        if content_type in DOCUMENT_TYPES or content_type in GENERIC_TYPES:
            return self.options.max_document_bytes
        return -1  # unsupported type: do not download the body

    async def fetch(self, link: Link, client: httpx.AsyncClient) -> FetchResult:
        """Fetch and extract ``link``."""
        try:
            response = await get_capped(
                client,
                link.url,
                cap=self._cap,
                headers={"Accept": "text/html,application/xhtml+xml,*/*;q=0.8"},
            )
        except BodyTooLarge as exc:
            result = FetchResult.skip(str(exc))
            result.fetcher = self.name
            return result
        return await extract_response(response, self.options)
