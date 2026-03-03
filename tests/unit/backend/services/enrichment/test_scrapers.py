"""Unit tests for YouTubeEnricher, LinkScraper, and XEnricher.

All HTTP calls are mocked with httpx.MockTransport so no real network
requests are made during tests.
"""

from unittest.mock import MagicMock, patch

import httpx
import pytest

from backend.postparse.services.enrichment.youtube import (
    YouTubeEnricher,
    is_youtube_url,
)
from backend.postparse.services.enrichment.link_scraper import LinkScraper
from backend.postparse.services.enrichment.x_twitter import (
    XEnricher,
    is_x_url,
    _to_fxtwitter_url,
)
from backend.postparse.services.enrichment.base import EnrichmentResult


# ============================================================================
# is_youtube_url
# ============================================================================


class TestIsYoutubeUrl:
    """Tests for the is_youtube_url helper."""

    def test_youtube_com(self) -> None:
        assert is_youtube_url("https://youtube.com/watch?v=abc") is True

    def test_www_youtube_com(self) -> None:
        assert is_youtube_url("https://www.youtube.com/watch?v=abc") is True

    def test_youtu_be(self) -> None:
        assert is_youtube_url("https://youtu.be/abc") is True

    def test_m_youtube(self) -> None:
        assert is_youtube_url("https://m.youtube.com/watch?v=abc") is True

    def test_not_youtube(self) -> None:
        assert is_youtube_url("https://github.com/repo") is False
        assert is_youtube_url("https://x.com/user/status/1") is False

    def test_empty(self) -> None:
        assert is_youtube_url("") is False


# ============================================================================
# YouTubeEnricher
# ============================================================================


class TestYouTubeEnricher:
    """Tests for YouTubeEnricher."""

    def _mock_transport(
        self,
        oembed_json: dict,
        page_html: str = "",
        oembed_status: int = 200,
        page_status: int = 200,
    ) -> httpx.MockTransport:
        """Build a mock transport that handles both oEmbed and page requests."""
        import json as _json

        def handler(request: httpx.Request) -> httpx.Response:
            if "oembed" in str(request.url):
                return httpx.Response(
                    oembed_status,
                    content=_json.dumps(oembed_json).encode(),
                    headers={"content-type": "application/json"},
                )
            return httpx.Response(
                page_status,
                content=page_html.encode(),
                headers={"content-type": "text/html"},
            )

        return httpx.MockTransport(handler)

    def _patched_client(self, transport) -> YouTubeEnricher:
        """Return enricher with httpx client patched to use mock transport."""
        enricher = YouTubeEnricher()

        def mock_get(url, **kwargs):
            with httpx.Client(transport=transport) as client:
                return client.get(url, **kwargs)

        enricher._get = mock_get
        return enricher

    def test_enrich_returns_result(self) -> None:
        """enrich() returns an EnrichmentResult with title and author."""
        oembed = {"title": "Test Video", "author_name": "Test Channel"}
        page_html = '<meta property="og:description" content="A great video.">'

        with patch("httpx.get") as mock_get:
            import json as _json

            def side_effect(url, **kwargs):
                r = MagicMock()
                if "oembed" in url:
                    r.json.return_value = oembed
                    r.raise_for_status = MagicMock()
                else:
                    r.text = page_html
                    r.raise_for_status = MagicMock()
                return r

            mock_get.side_effect = side_effect

            enricher = YouTubeEnricher()
            result = enricher.enrich("", "https://youtube.com/watch?v=abc")

        assert isinstance(result, EnrichmentResult)
        assert "Test Video" in result.generated_text
        assert "Test Channel" in result.generated_text
        assert "A great video." in result.generated_text
        assert result.metadata["title"] == "Test Video"
        assert result.metadata["author"] == "Test Channel"
        assert result.source_url == "https://youtube.com/watch?v=abc"

    def test_enrich_no_source_url_raises(self) -> None:
        """ValueError raised when source_url is missing."""
        with pytest.raises(ValueError, match="source_url is required"):
            YouTubeEnricher().enrich("some text")

    def test_enrich_non_youtube_url_raises(self) -> None:
        """ValueError raised when url is not YouTube."""
        with pytest.raises(ValueError, match="Not a YouTube URL"):
            YouTubeEnricher().enrich("", source_url="https://github.com")

    def test_description_fallback_when_page_fails(self) -> None:
        """enrich() still works when page fetch for description fails."""
        oembed = {"title": "Title Only", "author_name": "Chan"}

        with patch("httpx.get") as mock_get:
            call_count = [0]

            def side_effect(url, **kwargs):
                call_count[0] += 1
                r = MagicMock()
                if "oembed" in url:
                    r.json.return_value = oembed
                    r.raise_for_status = MagicMock()
                else:
                    r.raise_for_status.side_effect = Exception("403 Forbidden")
                return r

            mock_get.side_effect = side_effect

            enricher = YouTubeEnricher()
            result = enricher.enrich("", "https://youtube.com/watch?v=abc")

        assert "Title Only" in result.generated_text
        assert result.metadata["description"] is None


# ============================================================================
# _FullPageParser
# ============================================================================


class TestFullPageParser:
    """Tests for the HTML parsing logic in LinkScraper (via lxml)."""

    def test_extracts_og_title(self) -> None:
        html = '<html><head><meta property="og:title" content="My Title"></head><body></body></html>'
        with patch("httpx.get") as mock_get:
            r = MagicMock()
            r.text = html
            r.url = "https://example.com"
            r.raise_for_status = MagicMock()
            mock_get.return_value = r
            result = LinkScraper().enrich("", "https://example.com")
        assert result.metadata["title"] == "My Title"

    def test_extracts_og_description(self) -> None:
        html = '<html><head><meta property="og:description" content="My Description"></head><body></body></html>'
        with patch("httpx.get") as mock_get:
            r = MagicMock()
            r.text = html
            r.url = "https://example.com"
            r.raise_for_status = MagicMock()
            mock_get.return_value = r
            result = LinkScraper().enrich("", "https://example.com")
        assert result.metadata["description"] == "My Description"

    def test_extracts_meta_description(self) -> None:
        html = '<html><head><meta name="description" content="Fallback desc"></head><body></body></html>'
        with patch("httpx.get") as mock_get:
            r = MagicMock()
            r.text = html
            r.url = "https://example.com"
            r.raise_for_status = MagicMock()
            mock_get.return_value = r
            result = LinkScraper().enrich("", "https://example.com")
        assert result.metadata["description"] == "Fallback desc"

    def test_extracts_title_tag(self) -> None:
        html = "<html><head><title>Page Title</title></head><body></body></html>"
        with patch("httpx.get") as mock_get:
            r = MagicMock()
            r.text = html
            r.url = "https://example.com"
            r.raise_for_status = MagicMock()
            mock_get.return_value = r
            result = LinkScraper().enrich("", "https://example.com")
        assert result.metadata["title"] == "Page Title"

    def test_body_text_extracted(self) -> None:
        html = "<html><body><p>Hello world</p><p>Second para</p></body></html>"
        with patch("httpx.get") as mock_get:
            r = MagicMock()
            r.text = html
            r.url = "https://example.com"
            r.raise_for_status = MagicMock()
            mock_get.return_value = r
            result = LinkScraper().enrich("", "https://example.com")
        assert "Hello world" in result.generated_text
        assert "Second para" in result.generated_text

    def test_script_content_excluded(self) -> None:
        html = "<html><body><script>var x = 'secret';</script><p>Visible</p></body></html>"
        with patch("httpx.get") as mock_get:
            r = MagicMock()
            r.text = html
            r.url = "https://example.com"
            r.raise_for_status = MagicMock()
            mock_get.return_value = r
            result = LinkScraper().enrich("", "https://example.com")
        assert "secret" not in result.generated_text
        assert "Visible" in result.generated_text

    def test_nav_content_excluded(self) -> None:
        html = "<html><body><nav>Menu item</nav><p>Article</p></body></html>"
        with patch("httpx.get") as mock_get:
            r = MagicMock()
            r.text = html
            r.url = "https://example.com"
            r.raise_for_status = MagicMock()
            mock_get.return_value = r
            result = LinkScraper().enrich("", "https://example.com")
        assert "Menu item" not in result.generated_text
        assert "Article" in result.generated_text

    def test_body_text_respects_max_chars(self) -> None:
        html = f"<html><body><p>{'A' * 10000}</p></body></html>"
        with patch("httpx.get") as mock_get:
            r = MagicMock()
            r.text = html
            r.url = "https://example.com"
            r.raise_for_status = MagicMock()
            mock_get.return_value = r
            result = LinkScraper(max_body_chars=100).enrich("", "https://example.com")
        body_section = result.generated_text.split("Body:\n", 1)[-1]
        assert len(body_section) <= 100


# ============================================================================
# LinkScraper
# ============================================================================


class TestLinkScraper:
    """Tests for LinkScraper."""

    _SAMPLE_HTML = """
    <html>
    <head>
        <title>Fallback Title</title>
        <meta property="og:title" content="OG Title">
        <meta property="og:description" content="OG Description">
    </head>
    <body>
        <nav>Skip this nav content</nav>
        <article>
            <p>This is the main article text.</p>
            <p>Second paragraph of content.</p>
        </article>
        <script>ignore_this_script();</script>
    </body>
    </html>
    """

    def test_enrich_returns_result(self) -> None:
        """enrich() returns EnrichmentResult with all fields."""
        with patch("httpx.get") as mock_get:
            r = MagicMock()
            r.text = self._SAMPLE_HTML
            r.url = "https://example.com/article"
            r.raise_for_status = MagicMock()
            mock_get.return_value = r

            result = LinkScraper().enrich("", "https://example.com/article")

        assert isinstance(result, EnrichmentResult)
        assert result.metadata["title"] == "OG Title"
        assert result.metadata["description"] == "OG Description"
        assert "main article text" in result.generated_text
        assert "ignore_this_script" not in result.generated_text
        assert "Skip this nav content" not in result.generated_text

    def test_enrich_no_source_url_raises(self) -> None:
        """ValueError raised when source_url is missing."""
        with pytest.raises(ValueError, match="source_url is required"):
            LinkScraper().enrich("text only")

    def test_generated_text_structure(self) -> None:
        """generated_text contains Title, Description, Body sections."""
        with patch("httpx.get") as mock_get:
            r = MagicMock()
            r.text = self._SAMPLE_HTML
            r.url = "https://example.com"
            r.raise_for_status = MagicMock()
            mock_get.return_value = r

            result = LinkScraper().enrich("", "https://example.com")

        assert "Title:" in result.generated_text
        assert "Description:" in result.generated_text
        assert "Body:" in result.generated_text

    def test_fallback_title_from_title_tag(self) -> None:
        """Falls back to <title> tag when og:title is missing."""
        html = "<html><head><title>Plain Title</title></head><body><p>text</p></body></html>"
        with patch("httpx.get") as mock_get:
            r = MagicMock()
            r.text = html
            r.url = "https://example.com"
            r.raise_for_status = MagicMock()
            mock_get.return_value = r

            result = LinkScraper().enrich("", "https://example.com")

        assert result.metadata["title"] == "Plain Title"


# ============================================================================
# is_x_url
# ============================================================================


class TestIsXUrl:
    """Tests for the is_x_url helper."""

    def test_x_com(self) -> None:
        assert is_x_url("https://x.com/jack/status/20") is True

    def test_twitter_com(self) -> None:
        assert is_x_url("https://twitter.com/jack/status/20") is True

    def test_www_x_com(self) -> None:
        assert is_x_url("https://www.x.com/jack/status/20") is True

    def test_www_twitter_com(self) -> None:
        assert is_x_url("https://www.twitter.com/jack/status/20") is True

    def test_mobile_twitter(self) -> None:
        assert is_x_url("https://mobile.twitter.com/jack/status/20") is True

    def test_not_x(self) -> None:
        assert is_x_url("https://github.com/user") is False

    def test_empty(self) -> None:
        assert is_x_url("") is False


# ============================================================================
# _to_fxtwitter_url
# ============================================================================


class TestToFxtwitterUrl:
    """Tests for the _to_fxtwitter_url helper."""

    def test_x_com(self) -> None:
        assert _to_fxtwitter_url("https://x.com/jack/status/20") == \
            "https://fxtwitter.com/jack/status/20"

    def test_twitter_com(self) -> None:
        assert _to_fxtwitter_url("https://twitter.com/jack/status/20") == \
            "https://fxtwitter.com/jack/status/20"

    def test_preserves_path(self) -> None:
        result = _to_fxtwitter_url("https://x.com/user/status/12345")
        assert result == "https://fxtwitter.com/user/status/12345"


# ============================================================================
# XEnricher
# ============================================================================


class TestXEnricher:
    """Tests for XEnricher (mocked HTTP)."""

    _SAMPLE_HTML = """
    <html><head>
    <meta property="og:title" content="TestUser (@testuser)" />
    <meta property="og:description" content="This is a test tweet with some content" />
    <meta property="og:image" content="https://pbs.twimg.com/image.jpg" />
    </head><body></body></html>
    """

    def test_enrich_returns_result(self) -> None:
        """enrich() returns EnrichmentResult with tweet text."""
        with patch("backend.postparse.services.enrichment.x_twitter.httpx.get") as mock_get:
            r = MagicMock()
            r.text = self._SAMPLE_HTML
            r.raise_for_status = MagicMock()
            mock_get.return_value = r

            result = XEnricher().enrich("", "https://x.com/testuser/status/123")

        assert isinstance(result, EnrichmentResult)
        assert result.enricher_name == "x_enricher"
        assert "This is a test tweet" in result.generated_text
        assert result.metadata["author"] == "TestUser (@testuser)"
        assert result.metadata["tweet_text"] == "This is a test tweet with some content"

    def test_enrich_no_source_url_raises(self) -> None:
        """ValueError raised when source_url is missing."""
        with pytest.raises(ValueError, match="source_url is required"):
            XEnricher().enrich("text only")

    def test_enrich_non_x_url_raises(self) -> None:
        """ValueError raised for non-X URLs."""
        with pytest.raises(ValueError, match="Not an X/Twitter URL"):
            XEnricher().enrich("", "https://github.com/user")

    def test_enrich_deleted_tweet_raises(self) -> None:
        """RuntimeError raised when tweet doesn't exist."""
        html = """
        <html><head>
        <meta property="og:title" content="FxTwitter" />
        <meta property="og:description" content="Sorry, that post doesn't exist :(" />
        </head></html>
        """
        with patch("backend.postparse.services.enrichment.x_twitter.httpx.get") as mock_get:
            r = MagicMock()
            r.text = html
            r.raise_for_status = MagicMock()
            mock_get.return_value = r

            with pytest.raises(RuntimeError, match="not found or unavailable"):
                XEnricher().enrich("", "https://x.com/user/status/999")

    def test_uses_bot_user_agent(self) -> None:
        """Request is made with Twitterbot UA and no redirect follow."""
        with patch("backend.postparse.services.enrichment.x_twitter.httpx.get") as mock_get:
            r = MagicMock()
            r.text = self._SAMPLE_HTML
            r.raise_for_status = MagicMock()
            mock_get.return_value = r

            XEnricher().enrich("", "https://x.com/user/status/123")

        call_kwargs = mock_get.call_args
        assert "fxtwitter.com" in call_kwargs.args[0]
        assert call_kwargs.kwargs["follow_redirects"] is False
        assert "Twitterbot" in call_kwargs.kwargs["headers"]["User-Agent"]
