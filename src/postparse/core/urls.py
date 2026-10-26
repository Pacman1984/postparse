"""URL extraction and normalization helpers.

``normalize_url`` produces the key used to de-duplicate links in the database:
two URLs that differ only in tracking parameters, fragment, host case or query
parameter order map to the same normalized URL.

Example:
    >>> normalize_url("HTTPS://WWW.Example.com/a?utm_source=x&b=2&a=1#top")
    'https://www.example.com/a?a=1&b=2'
"""

from __future__ import annotations

import re
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

__all__ = ["TRACKING_PARAMS", "extract_urls", "normalize_url", "url_domain"]

#: Query parameters removed by :func:`normalize_url` (``utm_*`` is matched by prefix).
TRACKING_PARAMS: frozenset[str] = frozenset(
    {"fbclid", "gclid", "igshid", "igsh", "si", "ref_src"}
)

_URL_RE = re.compile(r"https?://[^\s<>\"'`]+", re.IGNORECASE)
_TRAILING_PUNCT = ".,;:!?'\"*"
_BRACKETS = {")": "(", "]": "[", "}": "{", ">": "<"}

# Common multi-label public suffixes; good enough for grouping by site.
_SECOND_LEVEL_SUFFIXES: frozenset[str] = frozenset(
    {
        "co.uk", "org.uk", "ac.uk", "gov.uk", "co.jp", "co.kr", "co.nz", "co.za",
        "co.in", "com.au", "net.au", "org.au", "com.br", "com.mx", "com.tr",
        "com.cn", "com.hk", "com.sg", "com.ar", "co.at", "or.at", "gv.at",
    }
)


def _strip_trailing(url: str) -> str:
    """Remove trailing punctuation and unbalanced closing brackets."""
    while url:
        last = url[-1]
        if last in _TRAILING_PUNCT:
            url = url[:-1]
            continue
        if last in _BRACKETS and url.count(last) > url.count(_BRACKETS[last]):
            url = url[:-1]
            continue
        break
    return url


def extract_urls(text: str | None) -> list[str]:
    """Extract http(s) URLs from free text.

    Trailing sentence punctuation and unbalanced closing brackets are removed,
    so ``"see (https://x.org/a)."`` yields ``https://x.org/a``. Duplicates are
    kept out; order of first appearance is preserved.

    Args:
        text: Text to scan; ``None`` yields an empty list.

    Returns:
        List of URLs as they appear in the text (not normalized).
    """
    if not text:
        return []
    seen: set[str] = set()
    result: list[str] = []
    for match in _URL_RE.finditer(text):
        url = _strip_trailing(match.group(0))
        parts = urlsplit(url)
        if not parts.netloc or url in seen:
            continue
        seen.add(url)
        result.append(url)
    return result


def _is_tracking_param(name: str) -> bool:
    """Return True for query parameter names that only carry tracking data."""
    lowered = name.lower()
    return lowered.startswith("utm_") or lowered in TRACKING_PARAMS


def normalize_url(url: str) -> str:
    """Normalize a URL for de-duplication.

    Lowercases scheme and host, drops default ports, the fragment and tracking
    parameters (``utm_*``, ``fbclid``, ``gclid``, ``igshid``, ``igsh``, ``si``,
    ``ref_src``), and sorts the remaining query parameters (stable for repeated
    keys). The path is kept as-is (an empty path becomes ``/``).

    Args:
        url: Absolute http(s) URL.

    Returns:
        Normalized URL.

    Raises:
        ValueError: If the URL is not an absolute http(s) URL.
    """
    parts = urlsplit(url.strip())
    scheme = parts.scheme.lower()
    if scheme not in ("http", "https") or not parts.hostname:
        raise ValueError(f"Not an absolute http(s) URL: {url!r}")
    host = parts.hostname.lower().rstrip(".")
    port = parts.port
    if port is not None and not (
        (scheme == "http" and port == 80) or (scheme == "https" and port == 443)
    ):
        host = f"{host}:{port}"
    if parts.username or parts.password:
        userinfo = parts.username or ""
        if parts.password:
            userinfo += f":{parts.password}"
        host = f"{userinfo}@{host}"
    params = [
        (key, value)
        for key, value in parse_qsl(parts.query, keep_blank_values=True)
        if not _is_tracking_param(key)
    ]
    params.sort(key=lambda kv: kv[0])
    query = urlencode(params, doseq=False)
    path = parts.path or "/"
    return urlunsplit((scheme, host, path, query, ""))


def url_domain(url: str) -> str:
    """Return the registrable-ish domain of a URL, without ``www.``.

    ``https://www.bbc.co.uk/news`` -> ``bbc.co.uk``;
    ``https://m.youtube.com/watch`` -> ``youtube.com``. IP addresses and
    single-label hosts are returned unchanged.

    Args:
        url: Absolute URL.

    Returns:
        Lowercase domain.

    Raises:
        ValueError: If the URL has no host.
    """
    host = urlsplit(url.strip()).hostname
    if not host:
        raise ValueError(f"URL has no host: {url!r}")
    host = host.lower().rstrip(".")
    if host.startswith("www."):
        host = host[4:]
    labels = host.split(".")
    if len(labels) <= 2 or all(label.isdigit() for label in labels) or ":" in host:
        return host
    last_two = ".".join(labels[-2:])
    if last_two in _SECOND_LEVEL_SUFFIXES:
        return ".".join(labels[-3:])
    return last_two
