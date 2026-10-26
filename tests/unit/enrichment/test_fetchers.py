"""Fetchers with respx-mocked HTTP: generic pages, documents, YouTube, X, Instagram."""

from __future__ import annotations

import json
from typing import Any

import httpx
import pytest
import respx

from postparse.core.db.models import Link
from postparse.core.urls import normalize_url, url_domain
from postparse.enrichment.fetchers import generic
from postparse.enrichment.fetchers.base import FetchResult
from postparse.enrichment.fetchers.documents import DocumentFetcher, document_extension
from postparse.enrichment.fetchers.generic import GenericFetcher, extract_html
from postparse.enrichment.fetchers.instagram import InstagramFetcher
from postparse.enrichment.fetchers.router import FetchRouter
from postparse.enrichment.fetchers.x import XFetcher, x_status_id
from postparse.enrichment.fetchers.youtube import YouTubeFetcher, youtube_video_id
from postparse.enrichment.options import EnrichmentOptions, default_user_agent
from tests.unit.enrichment.helpers import make_pdf

PARAGRAPH = (
    "Die Tomaten werden halbiert, mit Olivenöl beträufelt und bei 200 Grad für "
    "zwanzig Minuten im Ofen geröstet, bis sie leicht karamellisieren. "
)
ARTICLE = f"""<!doctype html>
<html lang="de"><head>
<meta charset="utf-8">
<title>Ofentomaten-Pasta | Kochblog</title>
<meta property="og:title" content="Ofentomaten-Pasta">
<meta name="author" content="Anna Koch">
<meta property="og:site_name" content="Kochblog">
<meta property="article:published_time" content="2026-03-14T10:00:00+01:00">
<meta name="description" content="Schnelle Pasta mit gerösteten Tomaten.">
</head><body>
<nav><a href="/">Start</a> <a href="/rezepte">Rezepte</a></nav>
<article>
<h1>Ofentomaten-Pasta</h1>
<p>{PARAGRAPH * 2}</p>
<p>Währenddessen die Spaghetti in reichlich Salzwasser al dente kochen und
anschließend mit den Tomaten, frischem Basilikum und Parmesan vermengen.</p>
<p>{PARAGRAPH}</p>
</article>
<footer>Impressum · Datenschutz</footer>
</body></html>"""

OPTIONS = EnrichmentOptions(min_domain_interval=0, concurrency=2, timeout=5)


def link(url: str) -> Link:
    normalized = normalize_url(url)
    return Link(1, normalized, url_domain(normalized))


async def fetch(fetcher: Any, url: str, options: EnrichmentOptions = OPTIONS) -> FetchResult:
    """Fetch through a router so error handling matches production."""
    async with FetchRouter([], fetcher, options) as router:
        return await router.fetch(link(url))


# -- generic -------------------------------------------------------------------------


@respx.mock
async def test_html_article_is_extracted_with_trafilatura() -> None:
    route = respx.get("https://kochblog.example/pasta").mock(
        return_value=httpx.Response(200, text=ARTICLE,
                                    headers={"content-type": "text/html; charset=utf-8"})
    )
    result = await fetch(GenericFetcher(OPTIONS), "https://kochblog.example/pasta")
    assert result.status == "ok" and result.fetcher == "generic"
    assert result.http_status == 200
    assert result.title == "Ofentomaten-Pasta"
    assert "Spaghetti in reichlich Salzwasser" in (result.text or "")
    assert "Impressum" not in (result.text or "")  # boilerplate removed
    meta = result.metadata
    assert meta["extractor"] == "trafilatura"
    assert meta["author"] == "Anna Koch" and meta["sitename"] == "Kochblog"
    assert meta["date"] == "2026-03-14"
    assert meta["final_url"] == "https://kochblog.example/pasta"
    # Honest User-Agent on the request.
    assert route.calls.last.request.headers["user-agent"] == default_user_agent()
    assert default_user_agent().startswith("postparse/")


def test_readability_fallback_when_trafilatura_finds_nothing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(generic, "_trafilatura", lambda html, url: ("", {}))
    result = extract_html(ARTICLE, "https://kochblog.example/pasta")
    assert result.status == "ok"
    assert result.metadata["extractor"] == "readability"
    assert "Spaghetti in reichlich Salzwasser" in (result.text or "")
    assert result.title  # readability's short title


def test_readability_used_when_trafilatura_crashes(monkeypatch: pytest.MonkeyPatch) -> None:
    def boom(html: str, url: str) -> Any:
        raise ValueError("broken tree")

    monkeypatch.setattr(generic, "_trafilatura", boom)
    result = extract_html(ARTICLE, "https://kochblog.example/pasta")
    assert result.status == "ok" and result.metadata["extractor"] == "readability"


def test_empty_page_is_skipped() -> None:
    result = extract_html("<html><body></body></html>", "https://e.example/")
    assert result.status == "skipped" and result.error == "no extractable content"


@respx.mock
async def test_redirects_are_followed_and_recorded() -> None:
    respx.get("https://short.example/abc").mock(
        return_value=httpx.Response(301, headers={"location": "https://kochblog.example/pasta"})
    )
    respx.get("https://kochblog.example/pasta").mock(
        return_value=httpx.Response(200, text=ARTICLE, headers={"content-type": "text/html"})
    )
    result = await fetch(GenericFetcher(OPTIONS), "https://short.example/abc")
    assert result.status == "ok"
    assert result.metadata["final_url"] == "https://kochblog.example/pasta"
    assert result.metadata["redirects"] == 1


@respx.mock
@pytest.mark.parametrize("code", [403, 404, 500])
async def test_http_errors_become_error_results(code: int) -> None:
    respx.get("https://e.example/x").mock(return_value=httpx.Response(code))
    result = await fetch(GenericFetcher(OPTIONS), "https://e.example/x")
    assert result.status == "error" and result.http_status == code
    assert result.error == f"HTTP {code}" and result.fetcher == "generic"


@respx.mock
async def test_timeout_becomes_error_result() -> None:
    respx.get("https://slow.example/").mock(side_effect=httpx.ReadTimeout("timed out"))
    result = await fetch(GenericFetcher(OPTIONS), "https://slow.example/")
    assert result.status == "error" and "timeout" in (result.error or "")


@respx.mock
async def test_connection_error_becomes_error_result() -> None:
    respx.get("https://down.example/").mock(side_effect=httpx.ConnectError("refused"))
    result = await fetch(GenericFetcher(OPTIONS), "https://down.example/")
    assert result.status == "error" and "ConnectError" in (result.error or "")


@respx.mock
async def test_body_size_cap() -> None:
    options = EnrichmentOptions(min_domain_interval=0, max_body_mb=0.01)  # ~10 KB
    big = "<html><body>" + "<p>x</p>" * 5000 + "</body></html>"
    respx.get("https://big.example/declared").mock(return_value=httpx.Response(
        200, text=big, headers={"content-type": "text/html"}))
    async def chunks() -> Any:
        yield big.encode()[:8000]
        yield big.encode()[8000:]

    respx.get("https://big.example/chunked").mock(return_value=httpx.Response(
        200, content=chunks(), headers={"content-type": "text/html"}))
    for url in ("https://big.example/declared", "https://big.example/chunked"):
        result = await fetch(GenericFetcher(options), url, options)
        assert result.status == "skipped", url
        assert "larger than" in (result.error or "")


@respx.mock
async def test_unsupported_content_type_is_skipped_without_body() -> None:
    respx.get("https://img.example/cat.jpg").mock(return_value=httpx.Response(
        200, content=b"\xff\xd8" * 10, headers={"content-type": "image/jpeg"}))
    result = await fetch(GenericFetcher(OPTIONS), "https://img.example/cat.jpg")
    assert result.status == "skipped" and "image/jpeg" in (result.error or "")


@respx.mock
async def test_plain_text_is_stored_as_is() -> None:
    respx.get("https://e.example/notes.txt").mock(return_value=httpx.Response(
        200, text="Zeile eins\n\n\n\nZeile zwei", headers={"content-type": "text/plain"}))
    result = await fetch(GenericFetcher(OPTIONS), "https://e.example/notes.txt")
    assert result.status == "ok" and result.text == "Zeile eins\n\nZeile zwei"


@respx.mock
async def test_latin1_page_is_decoded() -> None:
    html = ARTICLE.replace('<meta charset="utf-8">', "")
    respx.get("https://e.example/latin").mock(return_value=httpx.Response(
        200, content=html.encode("latin-1"),
        headers={"content-type": "text/html; charset=ISO-8859-1"}))
    result = await fetch(GenericFetcher(OPTIONS), "https://e.example/latin")
    assert "geröstet" in (result.text or "")


# -- documents -----------------------------------------------------------------------


def test_document_detection() -> None:
    assert document_extension("application/pdf", "https://e.example/x") == ".pdf"
    assert document_extension("application/octet-stream", "https://e.example/a.docx") == ".docx"
    assert document_extension("application/octet-stream", "https://e.example/a.bin") is None
    assert document_extension("text/html", "https://e.example/a.pdf") is None


@respx.mock
async def test_pdf_is_converted_with_markitdown_from_generic_handoff() -> None:
    respx.get("https://e.example/download?id=7").mock(return_value=httpx.Response(
        200, content=make_pdf("Hello Enrichment PDF"),
        headers={"content-type": "application/pdf"}))
    result = await fetch(GenericFetcher(OPTIONS), "https://e.example/download?id=7")
    assert result.status == "ok" and result.fetcher == "document"
    assert "Hello Enrichment PDF" in (result.text or "")
    assert result.metadata["format"] == "pdf" and result.metadata["extractor"] == "markitdown"


@respx.mock
async def test_document_fetcher_by_extension_and_size_cap() -> None:
    pdf = make_pdf("Second PDF")
    respx.get("https://e.example/files/report.pdf").mock(return_value=httpx.Response(
        200, content=pdf, headers={"content-type": "application/octet-stream"}))
    fetcher = DocumentFetcher(OPTIONS)
    assert fetcher.matches(link("https://e.example/files/report.pdf"))
    result = await fetch(fetcher, "https://e.example/files/report.pdf")
    assert result.status == "ok" and "Second PDF" in (result.text or "")
    assert result.title == "report.pdf"

    tiny = EnrichmentOptions(min_domain_interval=0, max_document_mb=0.0001)
    result = await fetch(DocumentFetcher(tiny), "https://e.example/files/report.pdf", tiny)
    assert result.status == "skipped" and "larger than" in (result.error or "")


@respx.mock
async def test_broken_document_is_skipped() -> None:
    respx.get("https://e.example/broken.pdf").mock(return_value=httpx.Response(
        200, content=b"%PDF-1.4 garbage", headers={"content-type": "application/pdf"}))
    result = await fetch(DocumentFetcher(OPTIONS), "https://e.example/broken.pdf")
    assert result.status == "skipped" and result.fetcher == "document"


# -- YouTube -------------------------------------------------------------------------


def test_youtube_video_ids() -> None:
    assert youtube_video_id("https://www.youtube.com/watch?v=dQw4w9WgXcQ&t=10") == "dQw4w9WgXcQ"
    assert youtube_video_id("https://youtu.be/dQw4w9WgXcQ") == "dQw4w9WgXcQ"
    assert youtube_video_id("https://youtube.com/shorts/dQw4w9WgXcQ") == "dQw4w9WgXcQ"
    assert youtube_video_id("https://m.youtube.com/embed/dQw4w9WgXcQ") == "dQw4w9WgXcQ"
    assert youtube_video_id("https://www.youtube.com/@channel") is None
    assert youtube_video_id("https://www.youtube.com/watch?v=short") is None


def _oembed() -> httpx.Response:
    return httpx.Response(200, json={
        "title": "Pasta in 10 Minuten", "author_name": "Kochkanal",
        "author_url": "https://www.youtube.com/@kochkanal",
        "thumbnail_url": "https://i.ytimg.com/vi/dQw4w9WgXcQ/hqdefault.jpg",
    })


@respx.mock
async def test_youtube_oembed_ytdlp_and_transcript() -> None:
    route = respx.get("https://www.youtube.com/oembed").mock(return_value=_oembed())
    seen: dict[str, Any] = {}

    def ytdlp(url: str) -> dict[str, Any]:
        seen["url"] = url
        return {
            "title": "Pasta in 10 Minuten", "description": "Alle Zutaten in der Beschreibung.",
            "upload_date": "20260301", "duration": 612, "tags": ["pasta", "rezept"],
            "chapters": [{"start_time": 0, "end_time": 65, "title": "Intro"},
                         {"start_time": 65, "end_time": 612, "title": "Kochen"}],
            "channel": "Kochkanal", "view_count": 1234,
        }

    def transcripts(video_id: str, languages: Any) -> tuple[str, str, bool]:
        seen["transcript"] = (video_id, tuple(languages))
        return ("de", "Hallo und willkommen in meiner Küche", True)

    fetcher = YouTubeFetcher(OPTIONS, ytdlp_extract=ytdlp, transcript_fetcher=transcripts)
    url = "https://youtu.be/dQw4w9WgXcQ?si=tracking"
    assert fetcher.matches(link(url))
    result = await fetch(fetcher, url)
    assert result.status == "ok" and result.fetcher == "youtube"
    assert result.title == "Pasta in 10 Minuten"
    assert route.calls.last.request.url.params["url"] == (
        "https://www.youtube.com/watch?v=dQw4w9WgXcQ")
    assert seen["url"] == "https://www.youtube.com/watch?v=dQw4w9WgXcQ"
    assert seen["transcript"] == ("dQw4w9WgXcQ", ("de", "en"))
    meta = result.metadata
    assert meta["channel"] == "Kochkanal" and meta["upload_date"] == "2026-03-01"
    assert meta["duration"] == 612 and meta["tags"] == ["pasta", "rezept"]
    assert meta["transcript_language"] == "de" and meta["transcript_generated"] is True
    text = result.text or ""
    assert text.startswith("Alle Zutaten")
    assert "1:05 Kochen" in text
    assert "Transcript (de):\nHallo und willkommen" in text


@respx.mock
async def test_youtube_without_ytdlp_and_transcript_still_ok() -> None:
    respx.get("https://www.youtube.com/oembed").mock(return_value=_oembed())

    def no_transcript(video_id: str, languages: Any) -> Any:
        raise RuntimeError("TranscriptsDisabled")

    fetcher = YouTubeFetcher(OPTIONS, ytdlp_extract=lambda url: None,
                             transcript_fetcher=no_transcript)
    result = await fetch(fetcher, "https://www.youtube.com/watch?v=dQw4w9WgXcQ")
    assert result.status == "ok" and result.title == "Pasta in 10 Minuten"
    assert result.text is None
    assert result.metadata["transcript_error"] == "RuntimeError"


@respx.mock
async def test_youtube_ytdlp_failure_falls_back_to_oembed() -> None:
    respx.get("https://www.youtube.com/oembed").mock(return_value=_oembed())

    def broken(url: str) -> Any:
        raise RuntimeError("Sign in to confirm you're not a bot")

    fetcher = YouTubeFetcher(OPTIONS, ytdlp_extract=broken,
                             transcript_fetcher=lambda vid, langs: None)
    result = await fetch(fetcher, "https://www.youtube.com/watch?v=dQw4w9WgXcQ")
    assert result.status == "ok" and "not a bot" in result.metadata["ytdlp_error"]


@respx.mock
async def test_unavailable_youtube_video_is_an_error() -> None:
    respx.get("https://www.youtube.com/oembed").mock(return_value=httpx.Response(404))
    fetcher = YouTubeFetcher(OPTIONS, ytdlp_extract=lambda url: None,
                             transcript_fetcher=lambda vid, langs: None)
    result = await fetch(fetcher, "https://www.youtube.com/watch?v=dQw4w9WgXcQ")
    assert result.status == "error" and result.http_status == 404


# -- X -------------------------------------------------------------------------------


FX_TWEET = {
    "code": 200, "message": "OK",
    "tweet": {
        "url": "https://x.com/chef/status/1790000000000000001",
        "id": "1790000000000000001",
        "text": "Mein neues Lieblingsrezept",
        "author": {"name": "Chef Koch", "screen_name": "chef"},
        "created_at": "Tue May 14 10:00:00 +0000 2026",
        "likes": 10, "retweets": 2, "replies": 1, "lang": "de",
        "media": {"all": [{"type": "photo", "url": "https://pbs.twimg.com/a.jpg",
                           "altText": "Teller mit Pasta"}]},
        "quote": {"url": "https://x.com/other/status/1",
                  "text": "Original-Post", "author": {"name": "Other", "screen_name": "other"}},
    },
}


def test_x_status_ids() -> None:
    assert x_status_id("https://x.com/chef/status/1790000000000000001?s=20") == (
        "1790000000000000001")
    assert x_status_id("https://twitter.com/i/web/status/42") == "42"
    assert x_status_id("https://x.com/chef") is None


@respx.mock
async def test_fxtwitter_json() -> None:
    respx.get("https://api.fxtwitter.com/status/1790000000000000001").mock(
        return_value=httpx.Response(200, json=FX_TWEET))
    fetcher = XFetcher()
    url = "https://twitter.com/chef/status/1790000000000000001"
    assert fetcher.matches(link(url))
    result = await fetch(fetcher, url)
    assert result.status == "ok" and result.fetcher == "x"
    assert result.title == "Chef Koch (@chef) on X"
    text = result.text or ""
    assert text.startswith("Mein neues Lieblingsrezept")
    assert "[Image: Teller mit Pasta]" in text
    assert "Quoting Other (@other):\nOriginal-Post" in text
    meta = result.metadata
    assert meta["source"] == "fxtwitter" and meta["author_handle"] == "chef"
    assert meta["media"][0]["type"] == "photo" and meta["quote"]["author_handle"] == "other"


@respx.mock
async def test_x_falls_back_to_oembed() -> None:
    respx.get("https://api.fxtwitter.com/status/42").mock(return_value=httpx.Response(500))
    oembed = respx.get("https://publish.twitter.com/oembed").mock(return_value=httpx.Response(
        200, json={
            "url": "https://twitter.com/chef/status/42", "author_name": "Chef Koch",
            "author_url": "https://twitter.com/chef",
            "html": '<blockquote class="twitter-tweet"><p lang="de">Pasta &amp; Wein</p>'
                    "&mdash; Chef Koch (@chef)</blockquote>",
        }))
    result = await fetch(XFetcher(), "https://x.com/chef/status/42")
    assert result.status == "ok" and result.text == "Pasta & Wein"
    assert result.metadata["source"] == "oembed"
    assert result.metadata["fxtwitter_error"] == "fxtwitter HTTP 500"
    assert oembed.calls.last.request.url.params["url"] == "https://twitter.com/i/status/42"


@respx.mock
async def test_x_both_sources_failing_is_an_error() -> None:
    respx.get("https://api.fxtwitter.com/status/42").mock(return_value=httpx.Response(
        404, json={"code": 404, "message": "NOT_FOUND"}))
    respx.get("https://publish.twitter.com/oembed").mock(return_value=httpx.Response(404))
    result = await fetch(XFetcher(), "https://x.com/chef/status/42")
    assert result.status == "error" and result.http_status == 404
    assert "fxtwitter HTTP 404" in (result.error or "")


async def test_x_profile_is_skipped() -> None:
    result = await fetch(XFetcher(), "https://x.com/chef")
    assert result.status == "skipped"


# -- Instagram -----------------------------------------------------------------------


@respx.mock(assert_all_called=False)
async def test_instagram_links_are_skipped_without_requests(respx_mock: Any) -> None:
    fetcher = InstagramFetcher()
    url = "https://www.instagram.com/p/C0dEx/"
    assert fetcher.matches(link(url)) and not fetcher.uses_network
    result = await fetch(fetcher, url)
    assert result.status == "skipped" and result.fetcher == "instagram"
    assert len(respx_mock.calls) == 0


def test_options_from_config() -> None:
    config = type("C", (), {"get_section": staticmethod(lambda name: {
        "concurrency": 2, "transcript_languages": "en, fr", "user_agent": "custom/1"})})()
    options = EnrichmentOptions.from_config(config)
    assert options.concurrency == 2 and options.transcript_languages == ("en", "fr")
    assert options.effective_user_agent == "custom/1"
    with pytest.raises(ValueError):
        EnrichmentOptions.from_config(type("C", (), {
            "get_section": staticmethod(lambda name: {"concurrency": 0})})())
    assert json.dumps(EnrichmentOptions().transcript_languages)
