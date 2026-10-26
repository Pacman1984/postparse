"""PDF and Office documents -> markdown text via markitdown.

Documents are recognized by content type or, for generic types such as
``application/octet-stream``, by the URL's file extension. The generic fetcher
hands such responses over to :func:`convert_document`; links whose URL already
ends in a document extension go straight to :class:`DocumentFetcher`.

markitdown runs in a worker thread (PDF parsing is CPU-bound) and with plugins
disabled.
"""

from __future__ import annotations

import asyncio
import io
import logging
from pathlib import PurePosixPath
from typing import Any
from urllib.parse import urlsplit

import httpx

from postparse.core.db.models import Link
from postparse.enrichment.fetchers.base import BodyTooLarge, FetchResult, get_capped, http_error
from postparse.enrichment.options import EnrichmentOptions

__all__ = [
    "DOCUMENT_EXTENSIONS",
    "DocumentFetcher",
    "convert_document",
    "document_extension",
]

logger = logging.getLogger(__name__)

#: Content type -> file extension of the documents markitdown converts.
DOCUMENT_TYPES: dict[str, str] = {
    "application/pdf": ".pdf",
    "application/x-pdf": ".pdf",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document": ".docx",
    "application/vnd.openxmlformats-officedocument.presentationml.presentation": ".pptx",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": ".xlsx",
    "application/vnd.ms-excel": ".xls",
    "application/epub+zip": ".epub",
}
#: File extensions treated as documents.
DOCUMENT_EXTENSIONS: frozenset[str] = frozenset(DOCUMENT_TYPES.values())
#: Text starting like this is the raw file, not converted content.
_RAW_MARKERS = ("%PDF", "PK\x03\x04", "\xd0\xcf\x11\xe0")
GENERIC_TYPES = frozenset(
    {
        "",
        "application/octet-stream",
        "binary/octet-stream",
        "application/download",
        "application/force-download",
    }
)


def url_extension(url: str) -> str:
    """Lower-case file extension of the URL path (``""`` if none)."""
    return PurePosixPath(urlsplit(url).path).suffix.lower()


def document_extension(content_type: str, url: str) -> str | None:
    """Return the document extension for a response, or ``None`` if it is no document.

    Args:
        content_type: Media type without parameters (lower case).
        url: Final URL (its extension decides for generic content types).
    """
    if content_type in DOCUMENT_TYPES:
        return DOCUMENT_TYPES[content_type]
    if content_type in GENERIC_TYPES:
        ext = url_extension(url)
        return ext if ext in DOCUMENT_EXTENSIONS else None
    return None


def _convert_sync(
    data: bytes, extension: str, mimetype: str | None, url: str
) -> tuple[str | None, str]:
    from markitdown import MarkItDown, StreamInfo

    converter = MarkItDown(enable_plugins=False)
    result = converter.convert_stream(
        io.BytesIO(data),
        stream_info=StreamInfo(extension=extension, mimetype=mimetype or None, url=url),
    )
    return (result.title or None), (result.text_content or "")


async def convert_document(
    data: bytes,
    *,
    extension: str,
    url: str,
    content_type: str | None = None,
    http_status: int | None = None,
    redirects: int = 0,
) -> FetchResult:
    """Convert document bytes to a :class:`FetchResult` (fetcher ``document``).

    Args:
        data: Document bytes.
        extension: File extension (``.pdf``, ``.docx``, ...).
        url: Final URL.
        content_type: Response content type.
        http_status: Response status.
        redirects: Redirects followed.

    Returns:
        ``ok`` with the markdown text, ``skipped`` if no text could be extracted.
    """
    metadata: dict[str, Any] = {
        "final_url": url,
        "content_type": content_type,
        "format": extension.lstrip("."),
        "size_bytes": len(data),
        "extractor": "markitdown",
    }
    if redirects:
        metadata["redirects"] = redirects
    try:
        title, text = await asyncio.to_thread(_convert_sync, data, extension, content_type, url)
    except Exception as exc:  # markitdown raises many converter-specific errors
        logger.debug("markitdown failed for %s", url, exc_info=True)
        result = FetchResult.skip(
            f"document conversion failed: {type(exc).__name__}: {exc}"[:500],
            http_status=http_status,
            **metadata,
        )
        result.fetcher = DocumentFetcher.name
        return result
    text = text.strip()
    if text.startswith(_RAW_MARKERS):
        # markitdown falls back to its plain-text converter for unparsable files.
        result = FetchResult.skip(
            "document could not be parsed", http_status=http_status, **metadata
        )
    elif not text:
        result = FetchResult.skip("document contains no text", http_status=http_status, **metadata)
    else:
        if not title:
            title = PurePosixPath(urlsplit(url).path).name or None
        result = FetchResult(
            "ok", http_status=http_status, title=title, text=text, metadata=metadata
        )
    result.fetcher = DocumentFetcher.name
    return result


class DocumentFetcher:
    """Fetch links whose URL ends in a document extension (``.pdf``, ``.docx``, ...).

    Args:
        options: Size caps.
    """

    name = "document"
    uses_network = True

    def __init__(self, options: EnrichmentOptions | None = None) -> None:
        self.options = options or EnrichmentOptions()

    def matches(self, link: Link) -> bool:
        """True for URLs with a document file extension."""
        return url_extension(link.url) in DOCUMENT_EXTENSIONS

    async def fetch(self, link: Link, client: httpx.AsyncClient) -> FetchResult:
        """Download and convert the document (HTML responses go to the generic fetcher)."""
        try:
            response = await get_capped(
                client, link.url, cap=lambda _type: self.options.max_document_bytes
            )
        except BodyTooLarge as exc:
            return self._named(FetchResult.skip(str(exc)))
        if response.status_code >= 400:
            return self._named(http_error(response.status_code))
        extension = document_extension(response.content_type, response.url) or (
            url_extension(link.url) if response.content_type in GENERIC_TYPES else None
        )
        if extension is None:
            from postparse.enrichment.fetchers.generic import extract_response

            return await extract_response(response, self.options)
        return await convert_document(
            response.content,
            extension=extension,
            url=response.url,
            content_type=response.content_type,
            http_status=response.status_code,
            redirects=response.redirects,
        )

    def _named(self, result: FetchResult) -> FetchResult:
        result.fetcher = self.name
        return result
