"""
Unit tests for CLI search commands.

This module tests search functionality for both Instagram posts and
Telegram messages with various filters.
"""

from unittest.mock import MagicMock, patch

import pytest
from click.testing import CliRunner

from backend.postparse.cli.main import cli


class TestSearchPosts:
    """Test search posts command."""

    def test_search_posts_without_filters(self) -> None:
        """
        Test searching posts without any filters.

        Tests the basic search functionality with mocked database.
        """
        runner = CliRunner()

        with patch("backend.postparse.cli.search.load_config") as mock_load:
            with patch("backend.postparse.cli.search.get_database") as mock_get_db:
                mock_config = MagicMock()
                mock_load.return_value = mock_config

                mock_db = MagicMock()
                mock_db.get_instagram_posts.return_value = [
                    {
                        "id": 1,
                        "caption": "Test post 1",
                        "owner_username": "user1",
                        "content_type": "image",
                        "likes": 100,
                        "date": "2024-01-15T10:00:00Z",
                    },
                    {
                        "id": 2,
                        "caption": "Test post 2",
                        "owner_username": "user2",
                        "content_type": "video",
                        "likes": 200,
                        "date": "2024-01-16T10:00:00Z",
                    },
                ]
                mock_get_db.return_value = mock_db

                result = runner.invoke(cli, ["search", "posts"])

                assert result.exit_code == 0
                # Should display results
                assert "2" in result.output or "post" in result.output.lower()

    def test_search_posts_with_hashtag_filter(self) -> None:
        """Test searching posts with hashtag filter."""
        runner = CliRunner()

        with patch("backend.postparse.cli.search.load_config") as mock_load:
            with patch("backend.postparse.cli.search.get_database") as mock_get_db:
                mock_config = MagicMock()
                mock_load.return_value = mock_config

                mock_db = MagicMock()
                mock_db.search_instagram_posts.return_value = (
                    [
                        {
                            "id": 1,
                            "caption": "Recipe post #cooking",
                            "owner_username": "chef",
                            "content_type": "image",
                            "likes": 50,
                            "date": "2024-01-20T10:00:00Z",
                        }
                    ],
                    None,
                )
                mock_get_db.return_value = mock_db

                result = runner.invoke(
                    cli, ["search", "posts", "--hashtag", "cooking"]
                )

                assert result.exit_code == 0
                # Should call search_instagram_posts with hashtag
                mock_db.search_instagram_posts.assert_called_once()

    def test_search_posts_with_multiple_hashtags(self) -> None:
        """Test searching posts with multiple hashtag filters."""
        runner = CliRunner()

        with patch("backend.postparse.cli.search.load_config") as mock_load:
            with patch("backend.postparse.cli.search.get_database") as mock_get_db:
                mock_config = MagicMock()
                mock_load.return_value = mock_config

                mock_db = MagicMock()
                mock_db.search_instagram_posts.return_value = ([], None)
                mock_get_db.return_value = mock_db

                result = runner.invoke(
                    cli,
                    [
                        "search",
                        "posts",
                        "--hashtag",
                        "recipe",
                        "--hashtag",
                        "cooking",
                    ],
                )

                assert result.exit_code == 0

    def test_search_posts_with_date_range(self) -> None:
        """Test searching posts with date range."""
        runner = CliRunner()

        with patch("backend.postparse.cli.search.load_config") as mock_load:
            with patch("backend.postparse.cli.search.get_database") as mock_get_db:
                mock_config = MagicMock()
                mock_load.return_value = mock_config

                mock_db = MagicMock()
                mock_db.search_instagram_posts.return_value = (
                    [
                        {
                            "id": 1,
                            "caption": "Post in range",
                            "date": "2024-06-15T10:00:00Z",
                        }
                    ],
                    None,
                )
                mock_get_db.return_value = mock_db

                result = runner.invoke(
                    cli,
                    [
                        "search",
                        "posts",
                        "--from",
                        "2024-01-01",
                        "--to",
                        "2024-12-31",
                    ],
                )

                assert result.exit_code == 0

    def test_search_posts_with_invalid_date(self) -> None:
        """Test searching posts with invalid date format."""
        runner = CliRunner()

        with patch("backend.postparse.cli.search.load_config") as mock_load:
            with patch("backend.postparse.cli.search.get_database") as mock_get_db:
                mock_config = MagicMock()
                mock_load.return_value = mock_config

                mock_db = MagicMock()
                mock_get_db.return_value = mock_db

                result = runner.invoke(
                    cli, ["search", "posts", "--from", "invalid-date"]
                )

                # click.Abort() gives exit code 1
                assert result.exit_code == 1
                # Should show error about invalid date
                assert "invalid" in result.output.lower() or "date" in result.output.lower()

    def test_search_posts_with_content_type_filter(self) -> None:
        """Test searching posts with content type filter."""
        runner = CliRunner()

        with patch("backend.postparse.cli.search.load_config") as mock_load:
            with patch("backend.postparse.cli.search.get_database") as mock_get_db:
                mock_config = MagicMock()
                mock_load.return_value = mock_config

                mock_db = MagicMock()
                mock_db.search_instagram_posts.return_value = (
                    [{"id": 1, "content_type": "video", "caption": "Video post"}],
                    None,
                )
                mock_get_db.return_value = mock_db

                result = runner.invoke(
                    cli, ["search", "posts", "--type", "video"]
                )

                assert result.exit_code == 0

    def test_search_posts_with_username_filter(self) -> None:
        """Test searching posts with username filter."""
        runner = CliRunner()

        with patch("backend.postparse.cli.search.load_config") as mock_load:
            with patch("backend.postparse.cli.search.get_database") as mock_get_db:
                mock_config = MagicMock()
                mock_load.return_value = mock_config

                mock_db = MagicMock()
                mock_db.search_instagram_posts.return_value = (
                    [{"id": 1, "owner_username": "testuser", "caption": "User post"}],
                    None,
                )
                mock_get_db.return_value = mock_db

                result = runner.invoke(
                    cli, ["search", "posts", "--username", "testuser"]
                )

                assert result.exit_code == 0

    def test_search_posts_json_output(self) -> None:
        """Test searching posts with JSON output format."""
        runner = CliRunner()

        with patch("backend.postparse.cli.search.load_config") as mock_load:
            with patch("backend.postparse.cli.search.get_database") as mock_get_db:
                mock_config = MagicMock()
                mock_load.return_value = mock_config

                mock_db = MagicMock()
                mock_db.get_instagram_posts.return_value = [
                    {"id": 1, "caption": "Test"}
                ]
                mock_get_db.return_value = mock_db

                result = runner.invoke(
                    cli, ["search", "posts", "--output", "json"]
                )

                assert result.exit_code == 0
                # Should output JSON
                assert "{" in result.output

    def test_search_posts_with_limit(self) -> None:
        """Test searching posts with result limit."""
        runner = CliRunner()

        with patch("backend.postparse.cli.search.load_config") as mock_load:
            with patch("backend.postparse.cli.search.get_database") as mock_get_db:
                mock_config = MagicMock()
                mock_load.return_value = mock_config

                mock_db = MagicMock()
                mock_db.get_instagram_posts.return_value = [
                    {"id": i, "caption": f"Post {i}"} for i in range(10)
                ]
                mock_get_db.return_value = mock_db

                result = runner.invoke(
                    cli, ["search", "posts", "--limit", "10"]
                )

                assert result.exit_code == 0
                # Should pass limit to database
                mock_db.get_instagram_posts.assert_called_with(limit=10)

    def test_search_posts_no_results(self) -> None:
        """Test searching posts when no results found."""
        runner = CliRunner()

        with patch("backend.postparse.cli.search.load_config") as mock_load:
            with patch("backend.postparse.cli.search.get_database") as mock_get_db:
                mock_config = MagicMock()
                mock_load.return_value = mock_config

                mock_db = MagicMock()
                mock_db.get_instagram_posts.return_value = []
                mock_get_db.return_value = mock_db

                result = runner.invoke(cli, ["search", "posts"])

                assert result.exit_code == 0
                # Should show no results message
                assert "no" in result.output.lower()


class TestSearchMessages:
    """Test search messages command."""

    def test_search_messages_without_filters(self) -> None:
        """Test searching messages without any filters."""
        runner = CliRunner()

        with patch("backend.postparse.cli.search.load_config") as mock_load:
            with patch("backend.postparse.cli.search.get_database") as mock_get_db:
                mock_config = MagicMock()
                mock_load.return_value = mock_config

                mock_db = MagicMock()
                mock_db.get_telegram_messages.return_value = [
                    {
                        "id": 1,
                        "text": "Test message 1",
                        "media_type": "text",
                        "views": 50,
                        "date": "2024-01-15T10:00:00Z",
                    },
                    {
                        "id": 2,
                        "text": "Test message 2",
                        "media_type": "photo",
                        "views": 100,
                        "date": "2024-01-16T10:00:00Z",
                    },
                ]
                mock_get_db.return_value = mock_db

                result = runner.invoke(cli, ["search", "messages"])

                assert result.exit_code == 0
                # Should display results
                assert "2" in result.output or "message" in result.output.lower()

    def test_search_messages_with_hashtag_filter(self) -> None:
        """Test searching messages with hashtag filter."""
        runner = CliRunner()

        with patch("backend.postparse.cli.search.load_config") as mock_load:
            with patch("backend.postparse.cli.search.get_database") as mock_get_db:
                mock_config = MagicMock()
                mock_load.return_value = mock_config

                mock_db = MagicMock()
                mock_db.search_telegram_messages.return_value = (
                    [
                        {
                            "id": 1,
                            "text": "Recipe message #cooking",
                            "media_type": "text",
                            "views": 25,
                            "date": "2024-01-20T10:00:00Z",
                        }
                    ],
                    None,
                )
                mock_get_db.return_value = mock_db

                result = runner.invoke(
                    cli, ["search", "messages", "--hashtag", "cooking"]
                )

                assert result.exit_code == 0

    def test_search_messages_with_content_type(self) -> None:
        """Test searching messages with content type filter."""
        runner = CliRunner()

        with patch("backend.postparse.cli.search.load_config") as mock_load:
            with patch("backend.postparse.cli.search.get_database") as mock_get_db:
                mock_config = MagicMock()
                mock_load.return_value = mock_config

                mock_db = MagicMock()
                mock_db.search_telegram_messages.return_value = (
                    [{"id": 1, "media_type": "photo", "caption": "Photo"}],
                    None,
                )
                mock_get_db.return_value = mock_db

                result = runner.invoke(
                    cli, ["search", "messages", "--type", "photo"]
                )

                assert result.exit_code == 0

    def test_search_messages_with_date_range(self) -> None:
        """Test searching messages with date range."""
        runner = CliRunner()

        with patch("backend.postparse.cli.search.load_config") as mock_load:
            with patch("backend.postparse.cli.search.get_database") as mock_get_db:
                mock_config = MagicMock()
                mock_load.return_value = mock_config

                mock_db = MagicMock()
                mock_db.search_telegram_messages.return_value = (
                    [{"id": 1, "text": "Message in range"}],
                    None,
                )
                mock_get_db.return_value = mock_db

                result = runner.invoke(
                    cli,
                    [
                        "search",
                        "messages",
                        "--from",
                        "2024-01-01",
                        "--to",
                        "2024-12-31",
                    ],
                )

                assert result.exit_code == 0

    def test_search_messages_json_output(self) -> None:
        """Test searching messages with JSON output."""
        runner = CliRunner()

        with patch("backend.postparse.cli.search.load_config") as mock_load:
            with patch("backend.postparse.cli.search.get_database") as mock_get_db:
                mock_config = MagicMock()
                mock_load.return_value = mock_config

                mock_db = MagicMock()
                mock_db.get_telegram_messages.return_value = [
                    {"id": 1, "text": "Test"}
                ]
                mock_get_db.return_value = mock_db

                result = runner.invoke(
                    cli, ["search", "messages", "--output", "json"]
                )

                assert result.exit_code == 0
                # Should output JSON
                assert "{" in result.output

    def test_search_messages_no_results(self) -> None:
        """Test searching messages when no results found."""
        runner = CliRunner()

        with patch("backend.postparse.cli.search.load_config") as mock_load:
            with patch("backend.postparse.cli.search.get_database") as mock_get_db:
                mock_config = MagicMock()
                mock_load.return_value = mock_config

                mock_db = MagicMock()
                mock_db.get_telegram_messages.return_value = []
                mock_get_db.return_value = mock_db

                result = runner.invoke(cli, ["search", "messages"])

                assert result.exit_code == 0
                # Should show no results message
                assert "no" in result.output.lower()


class TestSearchHelp:
    """Test search command help output."""

    def test_search_help_displays_subcommands(self) -> None:
        """Test that search --help shows available subcommands."""
        runner = CliRunner()
        result = runner.invoke(cli, ["search", "--help"])

        assert result.exit_code == 0
        output_lower = result.output.lower()
        assert "posts" in output_lower
        assert "messages" in output_lower

    def test_search_posts_help(self) -> None:
        """Test search posts --help displays help text."""
        runner = CliRunner()
        result = runner.invoke(cli, ["search", "posts", "--help"])

        assert result.exit_code == 0
        output_lower = result.output.lower()
        assert "posts" in output_lower
        assert "hashtag" in output_lower
        assert "limit" in output_lower

    def test_search_messages_help(self) -> None:
        """Test search messages --help displays help text."""
        runner = CliRunner()
        result = runner.invoke(cli, ["search", "messages", "--help"])

        assert result.exit_code == 0
        output_lower = result.output.lower()
        assert "messages" in output_lower
        assert "hashtag" in output_lower
        assert "type" in output_lower

