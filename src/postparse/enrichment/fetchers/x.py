"""X / Twitter posts via the fxtwitter JSON API, publish.twitter.com oEmbed as fallback.

``https://api.fxtwitter.com/status/<id>`` returns the post text, author,
media and quoted post without login. When it fails (deleted, private, API
down), ``https://publish.twitter.com/oembed`` still yields the text and author
of public posts. X links that are not posts (profiles, searches) are
``skipped``: x.com pages need JavaScript and a login.
"""

from __future__ import annotations

import logging
import re
from typing import Any
from urllib.parse import urlsplit

import httpx

from postparse.core.db.models import Link
from postparse.enrichment.fetchers.base import FetchResult

__all__ = ["XFetcher", "x_status_id"]

logger = logging.getLogger(__name__)

FXTWITTER_URL = "https://api.fxtwitter.com/status/{id}"
OEMBED_URL = "https://publish.twitter.com/oembed"
X_DOMAINS = frozenset(
    {
        "x.com",
        "twitter.com",
        "fxtwitter.com",
        "vxtwitter.com",
        "fixupx.com",
        "fixvx.com",
        "nitter.net",
    }
)
_STATUS_RE = re.compile(r"/status(?:es)?/(\d{1,25})")


def x_status_id(url: str) -> str | None:
    """Return the numeric post id of an X/Twitter status URL, or ``None``."""
    match = _STATUS_RE.search(urlsplit(url).path)
    return match.group(1) if match else None


def _author(data: dict[str, Any] | None) -> tuple[str | None, str | None]:
    if not isinstance(data, dict):
        return None, None
    return data.get("name") or None, data.get("screen_name") or None


def _tweet_text(tweet: dict[str, Any]) -> str:
    text = tweet.get("text")
    if not text and isinstance(tweet.get("raw_text"), dict):
        text = tweet["raw_text"].get("text")
    return (text or "").strip()


def _media(tweet: dict[str, Any]) -> list[dict[str, Any]]:
    media = tweet.get("media")
    items = media.get("all") if isinstance(media, dict) else None
    if not isinstance(items, list):
        return []
    result = []
    for entry in items:
        if not isinstance(entry, dict):
            continue
        item = {k: entry.get(k) for k in ("type", "url", "thumbnail_url", "altText", "duration")}
        result.append({k: v for k, v in item.items() if v not in (None, "")})
    return result


class XFetcher:
    """fxtwitter / oEmbed fetcher for X and Twitter posts."""

    name = "x"
    uses_network = True

    def matches(self, link: Link) -> bool:
        """All links on X/Twitter domains (non-posts are skipped)."""
        return link.domain in X_DOMAINS

    async def fetch(self, link: Link, client: httpx.AsyncClient) -> FetchResult:
        """Fetch the post text, author, media and quoted post."""
        status_id = x_status_id(link.url)
        if status_id is None:
            return self._named(
                FetchResult.skip("not an X post (profile/search pages need a login)")
            )
        fx_error: str | None = None
        try:
            response = await client.get(FXTWITTER_URL.format(id=status_id))
            if response.status_code == 200:
                payload = response.json()
                tweet = payload.get("tweet") if isinstance(payload, dict) else None
                if isinstance(tweet, dict) and (_tweet_text(tweet) or tweet.get("media")):
                    return self._from_fxtwitter(tweet, status_id, response.status_code)
                fx_error = "fxtwitter returned no post"
            else:
                fx_error = f"fxtwitter HTTP {response.status_code}"
        except (httpx.HTTPError, ValueError) as exc:
            fx_error = f"fxtwitter {type(exc).__name__}: {exc}"
        logger.debug("fxtwitter failed for %s (%s); trying oEmbed", status_id, fx_error)
        return await self._oembed(client, status_id, fx_error)

    def _from_fxtwitter(
        self, tweet: dict[str, Any], status_id: str, http_status: int
    ) -> FetchResult:
        name, handle = _author(tweet.get("author"))
        text = _tweet_text(tweet)
        metadata: dict[str, Any] = {
            "source": "fxtwitter",
            "id": status_id,
            "url": tweet.get("url"),
            "author": name,
            "author_handle": handle,
            "created_at": tweet.get("created_at"),
            "lang": tweet.get("lang"),
        }
        for key in ("likes", "retweets", "replies", "views"):
            if tweet.get(key) is not None:
                metadata[key] = tweet[key]
        media = _media(tweet)
        if media:
            metadata["media"] = media
        parts = [text] if text else []
        alt_texts = [m["altText"] for m in media if m.get("altText")]
        if alt_texts:
            parts.append("\n".join(f"[Image: {alt}]" for alt in alt_texts))
        quote = tweet.get("quote")
        if isinstance(quote, dict):
            q_name, q_handle = _author(quote.get("author"))
            q_text = _tweet_text(quote)
            metadata["quote"] = {
                "url": quote.get("url"),
                "author": q_name,
                "author_handle": q_handle,
                "text": q_text,
            }
            if q_text:
                parts.append(f"Quoting {q_name or ''} (@{q_handle or '?'}):\n{q_text}".strip())
        title = f"{name or handle or 'Unknown'} (@{handle or '?'}) on X"
        return FetchResult(
            "ok",
            fetcher=self.name,
            http_status=http_status,
            title=title,
            text="\n\n".join(parts) or None,
            metadata={k: v for k, v in metadata.items() if v is not None},
        )

    async def _oembed(
        self, client: httpx.AsyncClient, status_id: str, fx_error: str | None
    ) -> FetchResult:
        post_url = f"https://twitter.com/i/status/{status_id}"
        try:
            response = await client.get(
                OEMBED_URL, params={"url": post_url, "omit_script": "true", "dnt": "true"}
            )
        except httpx.HTTPError as exc:
            return self._named(
                FetchResult.failed(f"{fx_error}; oEmbed {type(exc).__name__}: {exc}", id=status_id)
            )
        if response.status_code != 200:
            return self._named(
                FetchResult.failed(
                    f"{fx_error}; oEmbed HTTP {response.status_code}",
                    http_status=response.status_code,
                    id=status_id,
                )
            )
        try:
            data = response.json()
        except ValueError:
            return self._named(FetchResult.failed(f"{fx_error}; oEmbed returned no JSON"))
        text = self._oembed_text(data.get("html") or "")
        author = data.get("author_name") or None
        author_url = data.get("author_url") or ""
        handle = author_url.rstrip("/").rsplit("/", 1)[-1] if author_url else None
        if not text and not author:
            return self._named(FetchResult.failed(f"{fx_error}; oEmbed returned no post"))
        return FetchResult(
            "ok",
            fetcher=self.name,
            http_status=response.status_code,
            title=f"{author or handle or 'Unknown'} (@{handle or '?'}) on X",
            text=text or None,
            metadata={
                k: v
                for k, v in {
                    "source": "oembed",
                    "id": status_id,
                    "url": data.get("url"),
                    "author": author,
                    "author_handle": handle,
                    "fxtwitter_error": fx_error,
                }.items()
                if v is not None
            },
        )

    @staticmethod
    def _oembed_text(html: str) -> str:
        if not html.strip():
            return ""
        from lxml import html as lxml_html

        tree = lxml_html.fromstring(html)
        paragraphs = tree.xpath("//blockquote//p")
        if not paragraphs:
            return tree.text_content().strip()
        return "\n".join(p.text_content().strip() for p in paragraphs).strip()

    def _named(self, result: FetchResult) -> FetchResult:
        result.fetcher = self.name
        return result
