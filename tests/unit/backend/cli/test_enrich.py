"""Unit tests for the enrich CLI command and URL extraction utility.

Tests cover:
- extract_urls() function for various URL formats
- content_expanded DB methods (save/get/pending items)
- CLI enrich urls command
"""

from contextlib import nullcontext
from pathlib import Path
from unittest.mock import MagicMock, call, patch

import pytest
from click.testing import CliRunner

from backend.postparse.cli.enrich import extract_urls
from backend.postparse.cli.main import cli
from backend.postparse.core.data.database import SocialMediaDatabase


# ============================================================================
# extract_urls() Tests
# ============================================================================


class TestExtractUrls:
    """Test the extract_urls utility function."""

    def test_extract_single_url(self) -> None:
        """Extracts a single URL from plain text."""
        urls = extract_urls("Check this out https://youtube.com/watch?v=abc123")
        assert urls == ["https://youtube.com/watch?v=abc123"]

    def test_extract_multiple_urls(self) -> None:
        """Extracts multiple URLs from text."""
        text = "See https://x.com/user/status/1 and https://github.com/repo"
        urls = extract_urls(text)
        assert len(urls) == 2
        assert "https://x.com/user/status/1" in urls
        assert "https://github.com/repo" in urls

    def test_extract_no_urls(self) -> None:
        """Returns empty list when no URLs present."""
        urls = extract_urls("This text has no links at all")
        assert urls == []

    def test_deduplicates_urls(self) -> None:
        """Same URL appearing twice is returned once."""
        text = "https://example.com and then again https://example.com"
        urls = extract_urls(text)
        assert urls == ["https://example.com"]

    def test_strips_trailing_punctuation(self) -> None:
        """Trailing punctuation is stripped from URLs."""
        urls = extract_urls("See https://example.com.")
        assert urls == ["https://example.com"]

        urls = extract_urls("(https://example.com)")
        assert urls == ["https://example.com"]

    def test_empty_input(self) -> None:
        """Returns empty list for empty/None input."""
        assert extract_urls("") == []
        assert extract_urls(None) == []

    def test_preserves_query_params(self) -> None:
        """Query parameters are kept in URLs."""
        url = "https://youtube.com/watch?v=abc123&t=42s"
        urls = extract_urls(f"Watch {url}")
        assert urls == [url]

    def test_bare_url_only(self) -> None:
        """Extracts URL when message is just a URL."""
        urls = extract_urls("https://x.com/user/status/1234567890")
        assert urls == ["https://x.com/user/status/1234567890"]

    def test_recognizes_various_domains(self) -> None:
        """Handles different URL domains correctly."""
        text = (
            "https://youtube.com/watch?v=1 "
            "https://x.com/u/status/1 "
            "https://github.com/repo "
            "https://arxiv.org/abs/2401.00001"
        )
        urls = extract_urls(text)
        assert len(urls) == 4


# ============================================================================
# Database content_expanded Tests
# ============================================================================


class TestContentExpandedDb:
    """Test content_expanded DB methods."""

    @pytest.fixture
    def db(self, tmp_path: Path) -> SocialMediaDatabase:
        """Create a temporary database."""
        return SocialMediaDatabase(str(tmp_path / "test.db"))

    def _insert_telegram_message(self, db: SocialMediaDatabase, content: str) -> int:
        """Insert a telegram message with a deterministic unique ID."""
        with db as database_ctx:
            database_ctx._cursor.execute(
                "SELECT COALESCE(MAX(message_id), 0) FROM telegram_messages"
            )
            row = database_ctx._cursor.fetchone()
        next_message_id = int(row[0]) + 1 if row else 1
        inserted_id = db._insert_telegram_message(
            message_id=next_message_id,
            content=content,
            content_type="text",
        )
        assert inserted_id is not None
        return inserted_id

    def _insert_instagram_post(self, db: SocialMediaDatabase, caption: str) -> int:
        """Insert an Instagram post with a deterministic shortcode."""
        with db as database_ctx:
            database_ctx._cursor.execute(
                "SELECT COALESCE(MAX(id), 0) FROM instagram_posts"
            )
            row = database_ctx._cursor.fetchone()
        shortcode_suffix = int(row[0]) + 1 if row else 1
        inserted_id = db._insert_instagram_post(
            shortcode=f"test_{shortcode_suffix}",
            caption=caption,
        )
        assert inserted_id is not None
        return inserted_id

    def test_save_and_get_content_expanded_telegram(
        self, db: SocialMediaDatabase
    ) -> None:
        """save/get content_expanded roundtrip for telegram."""
        item_id = self._insert_telegram_message(db, "Watch https://youtube.com/abc")
        db.save_content_expanded(item_id, 'telegram', 'https://youtube.com/abc')
        result = db.get_content_expanded(item_id, 'telegram')
        assert result == 'https://youtube.com/abc'

    def test_save_and_get_content_expanded_instagram(
        self, db: SocialMediaDatabase
    ) -> None:
        """save/get content_expanded roundtrip for instagram."""
        item_id = self._insert_instagram_post(db, "https://x.com/post/1")
        db.save_content_expanded(item_id, 'instagram', 'https://x.com/post/1')
        result = db.get_content_expanded(item_id, 'instagram')
        assert result == 'https://x.com/post/1'

    def test_get_content_expanded_none(self, db: SocialMediaDatabase) -> None:
        """Returns None when content_expanded not set."""
        item_id = self._insert_telegram_message(db, "No URL here")
        result = db.get_content_expanded(item_id, 'telegram')
        assert result is None

    def test_get_items_without_content_expanded(
        self, db: SocialMediaDatabase
    ) -> None:
        """Returns items with content but no content_expanded."""
        id1 = self._insert_telegram_message(db, "https://youtube.com/abc")
        id2 = self._insert_telegram_message(db, "https://x.com/1")
        id3 = self._insert_telegram_message(db, "No URL here")

        items = db.get_items_without_content_expanded('telegram')
        ids = {item['id'] for item in items}
        assert id1 in ids
        assert id2 in ids
        assert id3 in ids

    def test_already_expanded_not_returned(self, db: SocialMediaDatabase) -> None:
        """Items with content_expanded already set are excluded."""
        id1 = self._insert_telegram_message(db, "https://youtube.com/abc")
        id2 = self._insert_telegram_message(db, "https://x.com/1")
        db.save_content_expanded(id1, 'telegram', 'https://youtube.com/abc')

        items = db.get_items_without_content_expanded('telegram')
        ids = {item['id'] for item in items}
        assert id1 not in ids
        assert id2 in ids

    def test_content_expanded_table_has_column(
        self, db: SocialMediaDatabase
    ) -> None:
        """content_expanded column exists on both tables."""
        with db as d:
            d._cursor.execute("PRAGMA table_info(telegram_messages)")
            cols = {row[1] for row in d._cursor.fetchall()}
            assert 'content_expanded' in cols

            d._cursor.execute("PRAGMA table_info(instagram_posts)")
            cols = {row[1] for row in d._cursor.fetchall()}
            assert 'content_expanded' in cols


# ============================================================================
# CLI enrich urls Tests
# ============================================================================


class TestEnrichUrlsCli:
    """Test CLI enrich urls command."""

    def test_enrich_urls_help(self) -> None:
        """enrich urls --help displays options."""
        runner = CliRunner()
        result = runner.invoke(cli, ["enrich", "urls", "--help"])
        assert result.exit_code == 0
        assert "source" in result.output.lower()
        assert "limit" in result.output.lower()
        assert "force" in result.output.lower()

    def test_enrich_help_shows_urls_subcommand(self) -> None:
        """enrich --help shows urls subcommand."""
        runner = CliRunner()
        result = runner.invoke(cli, ["enrich", "--help"])
        assert result.exit_code == 0
        assert "urls" in result.output.lower()

    def test_enrich_urls_no_items(self) -> None:
        """enrich urls handles empty database gracefully."""
        runner = CliRunner()
        with patch("backend.postparse.cli.enrich.load_config") as mock_load:
            with patch("backend.postparse.cli.enrich.get_database") as mock_get_db:
                mock_config = MagicMock()
                mock_load.return_value = mock_config

                mock_db = MagicMock()
                mock_get_db.return_value = mock_db

                with patch(
                    "backend.postparse.cli.enrich._fetch_content_items",
                    return_value=[],
                ) as mock_fetch:
                    with patch(
                        "backend.postparse.cli.enrich._extract_and_cache_urls"
                    ) as mock_extract:
                        result = runner.invoke(
                            cli,
                            ["enrich", "urls", "--source", "telegram"],
                        )
                assert result.exit_code == 0
                output_lower = result.output.lower()
                assert "no telegram items to process" in output_lower
                assert "done. 0 items enriched with urls" in output_lower
                mock_fetch.assert_called_once_with(mock_db, "telegram", None)
                mock_extract.assert_not_called()

    def test_enrich_urls_skips_existing_without_force(self) -> None:
        """Skip rows with existing content_expanded when force is disabled."""
        runner = CliRunner()
        items = [
            {
                "id": 1,
                "content": "Existing https://example.com/old",
                "content_expanded": "already-expanded",
            },
            {
                "id": 2,
                "content": "New https://example.com/new",
                "content_expanded": "",
            },
        ]

        mock_progress = MagicMock()
        mock_progress.add_task.return_value = "task"
        with patch("backend.postparse.cli.enrich.load_config", return_value=MagicMock()):
            mock_db = MagicMock()
            with patch(
                "backend.postparse.cli.enrich.get_database",
                return_value=mock_db,
            ):
                with patch(
                    "backend.postparse.cli.enrich._fetch_content_items",
                    return_value=items,
                ):
                    with patch(
                        "backend.postparse.cli.enrich.create_progress",
                        return_value=nullcontext(mock_progress),
                    ):
                        result = runner.invoke(
                            cli,
                            ["enrich", "urls", "--source", "telegram"],
                        )

        assert result.exit_code == 0
        mock_db.save_content_expanded.assert_called_once_with(
            item_id=2,
            source="telegram",
            content_expanded="https://example.com/new",
        )
        assert "already processed" in result.output.lower()

    def test_enrich_urls_processes_existing_with_force(self) -> None:
        """Process rows with existing content_expanded when force is enabled."""
        runner = CliRunner()
        items = [
            {
                "id": 1,
                "content": "Existing https://example.com/old",
                "content_expanded": "already-expanded",
            },
            {
                "id": 2,
                "content": "New https://example.com/new",
                "content_expanded": "",
            },
        ]

        mock_progress = MagicMock()
        mock_progress.add_task.return_value = "task"
        with patch("backend.postparse.cli.enrich.load_config", return_value=MagicMock()):
            mock_db = MagicMock()
            with patch(
                "backend.postparse.cli.enrich.get_database",
                return_value=mock_db,
            ):
                with patch(
                    "backend.postparse.cli.enrich._fetch_content_items",
                    return_value=items,
                ):
                    with patch(
                        "backend.postparse.cli.enrich.create_progress",
                        return_value=nullcontext(mock_progress),
                    ):
                        result = runner.invoke(
                            cli,
                            ["enrich", "urls", "--source", "telegram", "--force"],
                        )

        assert result.exit_code == 0
        assert mock_db.save_content_expanded.call_count == 2
        mock_db.save_content_expanded.assert_has_calls(
            [
                call(
                    item_id=1,
                    source="telegram",
                    content_expanded="https://example.com/old",
                ),
                call(
                    item_id=2,
                    source="telegram",
                    content_expanded="https://example.com/new",
                ),
            ],
            any_order=False,
        )
        assert "already processed" in result.output.lower()
