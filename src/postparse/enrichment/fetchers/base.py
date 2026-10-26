"""Common types of the link fetchers: results, the fetcher protocol, capped HTTP reads.

A fetcher turns one URL into a :class:`FetchResult` (``ok`` / ``error`` /
``skipped`` plus title, text and metadata). Expected failures (HTTP errors,
timeouts, unsupported content) are returned as results; the router converts
unexpected exceptions into ``error`` results as well, so one bad page never
ends a run.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, Literal, Protocol, runtime_checkable

import httpx

from postparse.core.db.models import Link

__all__ = [
    "BodyTooLarge",
    "CappedResponse",
    "FetchResult",
    "Fetcher",
    "FetchStatusName",
    "charset_of",
    "decode_body",
    "get_capped",
    "http_error",
]

FetchStatusName = Literal["ok", "error", "skipped"]

_CHARSET_RE = re.compile(r"charset=[\"']?([\w.:-]+)", re.IGNORECASE)
_CHUNK = 1 << 16


@dataclass(slots=True)
class FetchResult:
    """Outcome of fetching one link.

    Attributes:
        status: ``ok``, ``error`` (retried with backoff) or ``skipped`` (final).
        fetcher: Name stored in ``link_fetches.fetcher`` (set by the fetcher).
        http_status: Final HTTP status, if a request was made.
        title: Page/document/video title.
        text: Extracted text (markdown-ish).
        metadata: JSON-serializable details (author, date, site, final URL, ...).
        error: Error / skip reason.
    """

    status: FetchStatusName
    fetcher: str = ""
    http_status: int | None = None
    title: str | None = None
    text: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
    error: str | None = None

    @classmethod
    def failed(cls, error: str, *, http_status: int | None = None, **metadata: Any) -> FetchResult:
        """An ``error`` result (retried later)."""
        return cls("error", http_status=http_status, error=error, metadata=dict(metadata))

    @classmethod
    def skip(cls, reason: str, *, http_status: int | None = None, **metadata: Any) -> FetchResult:
        """A ``skipped`` result (not retried)."""
        return cls("skipped", http_status=http_status, error=reason, metadata=dict(metadata))


@runtime_checkable
class Fetcher(Protocol):
    """A link fetcher.

    Attributes:
        name: Stored as ``link_fetches.fetcher``.
        uses_network: ``False`` for fetchers that never make requests (no throttling).
    """

    name: str
    uses_network: bool

    def matches(self, link: Link) -> bool:
        """True if this fetcher handles ``link``."""
        ...

    async def fetch(self, link: Link, client: httpx.AsyncClient) -> FetchResult:
        """Fetch ``link`` and return the result."""
        ...


class BodyTooLarge(Exception):
    """The response body exceeds the cap."""

    def __init__(self, size: int, cap: int) -> None:
        super().__init__(f"response larger than {cap / 1e6:.1f} MB ({size / 1e6:.1f} MB+)")
        self.size = size
        self.cap = cap


@dataclass(slots=True)
class CappedResponse:
    """A fully read response.

    Attributes:
        status_code: HTTP status.
        url: Final URL after redirects.
        headers: Response headers.
        content: Body bytes (at most the cap).
        redirects: Number of redirects followed.
    """

    status_code: int
    url: str
    headers: httpx.Headers
    content: bytes
    redirects: int = 0

    @property
    def content_type(self) -> str:
        """Lower-case media type without parameters (``""`` if missing)."""
        return self.headers.get("content-type", "").split(";", 1)[0].strip().lower()


async def get_capped(
    client: httpx.AsyncClient,
    url: str,
    *,
    cap: int | Callable[[str], int],
    headers: dict[str, str] | None = None,
) -> CappedResponse:
    """GET ``url`` (redirects follow the client setting) and read at most ``cap`` bytes.

    Args:
        client: HTTP client.
        url: URL.
        cap: Byte cap, or a callable ``content_type -> cap`` to choose the cap
            once the headers are known (documents may be larger than HTML).
            A negative cap skips the body (unsupported content types).
        headers: Extra request headers.

    Returns:
        Response with the body read.

    Raises:
        BodyTooLarge: The declared or actual size exceeds the cap.
        httpx.HTTPError: Transport errors and timeouts.
    """
    async with client.stream("GET", url, headers=headers) as response:
        content_type = response.headers.get("content-type", "").split(";", 1)[0].strip().lower()
        limit = int(cap(content_type)) if callable(cap) else int(cap)
        length = response.headers.get("content-length", "")
        if limit >= 0 and length.isdigit() and int(length) > limit:
            raise BodyTooLarge(int(length), limit)
        chunks: list[bytes] = []
        size = 0
        if response.status_code < 400 and limit >= 0:
            async for chunk in response.aiter_bytes(_CHUNK):
                size += len(chunk)
                if size > limit:
                    raise BodyTooLarge(size, limit)
                chunks.append(chunk)
        return CappedResponse(
            status_code=response.status_code,
            url=str(response.url),
            headers=response.headers,
            content=b"".join(chunks),
            redirects=len(response.history),
        )


def charset_of(headers: httpx.Headers) -> str | None:
    """Return the charset declared in ``Content-Type`` (``None`` if absent)."""
    match = _CHARSET_RE.search(headers.get("content-type", ""))
    return match.group(1) if match else None


def decode_body(content: bytes, charset: str | None = None) -> str:
    """Decode a body: declared charset, then UTF-8, then charset detection."""
    if charset:
        try:
            return content.decode(charset)
        except (LookupError, UnicodeDecodeError):
            pass
    try:
        return content.decode("utf-8")
    except UnicodeDecodeError:
        from charset_normalizer import from_bytes

        best = from_bytes(content).best()
        return str(best) if best is not None else content.decode("utf-8", errors="replace")


def http_error(status_code: int) -> FetchResult:
    """An ``error`` result for an HTTP error status."""
    return FetchResult.failed(f"HTTP {status_code}", http_status=status_code)
