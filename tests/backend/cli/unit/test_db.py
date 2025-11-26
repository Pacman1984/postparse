"""
Unit tests for CLI database commands.

This module tests database operations including statistics display,
data export, and database management commands.
"""

from pathlib import Path
from unittest.mock import MagicMock, mock_open, patch

import pytest
from click.testing import CliRunner

from backend.postparse.cli.main import cli


class TestDbStats:
    """Test db stats command."""

    def test_db_stats_displays_counts(self) -> None:
        """
        Test that db stats displays post and message counts.

        Mocks database at the boundary and tests display logic.
        """
        runner = CliRunner()

        with patch("backend.postparse.cli.db.load_config") as mock_load:
            with patch("backend.postparse.cli.db.get_database") as mock_get_db:
                mock_config = MagicMock()
                mock_config.get.return_value = "data/test.db"
                mock_load.return_value = mock_config

                mock_db = MagicMock()
                mock_db.get_instagram_posts.return_value = [
                    {"id": 1, "caption": "Test 1", "date": "2024-01-15T10:00:00Z", "content_type": "image"},
                    {"id": 2, "caption": "Test 2", "date": "2024-01-16T10:00:00Z", "content_type": "video"},
                ]
                mock_db.get_telegram_messages.return_value = [
                    {"id": 1, "text": "Message 1", "date": "2024-01-17T10:00:00Z", "media_type": "text"},
                ]
                mock_get_db.return_value = mock_db

                result = runner.invoke(cli, ["db", "stats"])

                assert result.exit_code == 0
                # Should display counts
                assert "2" in result.output  # 2 posts
                assert "1" in result.output  # 1 message

    def test_db_stats_with_empty_database(self) -> None:
        """Test db stats with empty database shows helpful message."""
        runner = CliRunner()

        with patch("backend.postparse.cli.db.load_config") as mock_load:
            with patch("backend.postparse.cli.db.get_database") as mock_get_db:
                mock_config = MagicMock()
                mock_config.get.return_value = "data/test.db"
                mock_load.return_value = mock_config

                mock_db = MagicMock()
                mock_db.get_instagram_posts.return_value = []
                mock_db.get_telegram_messages.return_value = []
                mock_get_db.return_value = mock_db

                result = runner.invoke(cli, ["db", "stats"])

                assert result.exit_code == 0
                # Should show empty message and help
                assert "empty" in result.output.lower() or "extract" in result.output.lower()

    def test_db_stats_shows_date_ranges(self) -> None:
        """Test that stats displays date ranges for posts and messages."""
        runner = CliRunner()

        with patch("backend.postparse.cli.db.load_config") as mock_load:
            with patch("backend.postparse.cli.db.get_database") as mock_get_db:
                mock_config = MagicMock()
                mock_config.get.return_value = "data/test.db"
                mock_load.return_value = mock_config

                mock_db = MagicMock()
                mock_db.get_instagram_posts.return_value = [
                    {"id": 1, "date": "2024-01-01T10:00:00Z", "content_type": "image"},
                    {"id": 2, "date": "2024-12-31T10:00:00Z", "content_type": "image"},
                ]
                mock_db.get_telegram_messages.return_value = [
                    {"id": 1, "date": "2024-06-15T10:00:00Z", "media_type": "text"},
                ]
                mock_get_db.return_value = mock_db

                result = runner.invoke(cli, ["db", "stats"])

                assert result.exit_code == 0
                # Should show date information
                assert "2024" in result.output

    def test_db_stats_shows_content_type_breakdown(self) -> None:
        """Test that stats shows breakdown by content type."""
        runner = CliRunner()

        with patch("backend.postparse.cli.db.load_config") as mock_load:
            with patch("backend.postparse.cli.db.get_database") as mock_get_db:
                mock_config = MagicMock()
                mock_config.get.return_value = "data/test.db"
                mock_load.return_value = mock_config

                mock_db = MagicMock()
                mock_db.get_instagram_posts.return_value = [
                    {"id": 1, "content_type": "image"},
                    {"id": 2, "content_type": "image"},
                    {"id": 3, "content_type": "video"},
                ]
                mock_db.get_telegram_messages.return_value = []
                mock_get_db.return_value = mock_db

                result = runner.invoke(cli, ["db", "stats"])

                assert result.exit_code == 0
                # Should show content types
                output_lower = result.output.lower()
                assert "image" in output_lower or "video" in output_lower

    def test_db_stats_detailed_shows_hashtags(self) -> None:
        """Test that stats --detailed shows hashtag distribution."""
        runner = CliRunner()

        with patch("backend.postparse.cli.db.load_config") as mock_load:
            with patch("backend.postparse.cli.db.get_database") as mock_get_db:
                mock_config = MagicMock()
                mock_config.get.return_value = "data/test.db"
                mock_load.return_value = mock_config

                mock_db = MagicMock()
                mock_db.get_instagram_posts.return_value = [{"id": 1}]
                mock_db.get_telegram_messages.return_value = []
                mock_db.get_all_hashtags.return_value = ["recipe", "cooking", "food", "recipe"]
                mock_get_db.return_value = mock_db

                result = runner.invoke(cli, ["db", "stats", "--detailed"])

                assert result.exit_code == 0
                # Should show hashtags
                output_lower = result.output.lower()
                assert "hashtag" in output_lower or "recipe" in output_lower

    def test_db_stats_handles_database_error(self) -> None:
        """Test that stats handles database errors gracefully."""
        runner = CliRunner()

        with patch("backend.postparse.cli.db.load_config") as mock_load:
            with patch("backend.postparse.cli.db.get_database") as mock_get_db:
                mock_config = MagicMock()
                mock_load.return_value = mock_config

                mock_get_db.side_effect = Exception("Database error")

                result = runner.invoke(cli, ["db", "stats"])

                # Should handle error
                assert result.exit_code != 0


class TestDbExport:
    """Test db export command."""

    def test_db_export_json_format(self, tmp_path: Path) -> None:
        """
        Test exporting database to JSON format.

        Tests actual export logic with mocked database data.
        """
        output_file = tmp_path / "export.json"

        runner = CliRunner()

        with patch("backend.postparse.cli.db.load_config") as mock_load:
            with patch("backend.postparse.cli.db.get_database") as mock_get_db:
                mock_config = MagicMock()
                mock_load.return_value = mock_config

                mock_db = MagicMock()
                mock_db.get_instagram_posts.return_value = [
                    {"id": 1, "caption": "Test post"},
                ]
                mock_db.get_telegram_messages.return_value = [
                    {"id": 1, "text": "Test message"},
                ]
                mock_get_db.return_value = mock_db

                result = runner.invoke(
                    cli,
                    ["db", "export", str(output_file), "--format", "json"]
                )

                assert result.exit_code == 0
                # Check file was created
                assert output_file.exists()

    def test_db_export_csv_format(self, tmp_path: Path) -> None:
        """Test exporting database to CSV format."""
        output_file = tmp_path / "export.csv"

        runner = CliRunner()

        with patch("backend.postparse.cli.db.load_config") as mock_load:
            with patch("backend.postparse.cli.db.get_database") as mock_get_db:
                mock_config = MagicMock()
                mock_load.return_value = mock_config

                mock_db = MagicMock()
                mock_db.get_instagram_posts.return_value = [
                    {"id": 1, "caption": "Test post", "likes": 10},
                ]
                mock_db.get_telegram_messages.return_value = [
                    {"id": 1, "text": "Test message", "views": 5},
                ]
                mock_get_db.return_value = mock_db

                result = runner.invoke(
                    cli,
                    ["db", "export", str(output_file), "--format", "csv", "--source", "all"]
                )

                assert result.exit_code == 0
                # Should create separate files for posts and messages
                assert (tmp_path / "export_posts.csv").exists() or output_file.exists()

    def test_db_export_posts_only(self, tmp_path: Path) -> None:
        """Test exporting only Instagram posts."""
        output_file = tmp_path / "posts_export.json"

        runner = CliRunner()

        with patch("backend.postparse.cli.db.load_config") as mock_load:
            with patch("backend.postparse.cli.db.get_database") as mock_get_db:
                mock_config = MagicMock()
                mock_load.return_value = mock_config

                mock_db = MagicMock()
                mock_db.get_instagram_posts.return_value = [
                    {"id": 1, "caption": "Test post"},
                ]
                mock_get_db.return_value = mock_db

                result = runner.invoke(
                    cli,
                    ["db", "export", str(output_file), "--source", "posts"]
                )

                assert result.exit_code == 0
                assert output_file.exists()

    def test_db_export_messages_only(self, tmp_path: Path) -> None:
        """Test exporting only Telegram messages."""
        output_file = tmp_path / "messages_export.json"

        runner = CliRunner()

        with patch("backend.postparse.cli.db.load_config") as mock_load:
            with patch("backend.postparse.cli.db.get_database") as mock_get_db:
                mock_config = MagicMock()
                mock_load.return_value = mock_config

                mock_db = MagicMock()
                mock_db.get_telegram_messages.return_value = [
                    {"id": 1, "text": "Test message"},
                ]
                mock_get_db.return_value = mock_db

                result = runner.invoke(
                    cli,
                    ["db", "export", str(output_file), "--source", "messages"]
                )

                assert result.exit_code == 0
                assert output_file.exists()

    def test_db_export_with_limit(self, tmp_path: Path) -> None:
        """Test exporting with record limit."""
        output_file = tmp_path / "limited_export.json"

        runner = CliRunner()

        with patch("backend.postparse.cli.db.load_config") as mock_load:
            with patch("backend.postparse.cli.db.get_database") as mock_get_db:
                mock_config = MagicMock()
                mock_load.return_value = mock_config

                mock_db = MagicMock()
                # Return multiple records but limit should apply
                mock_db.get_instagram_posts.return_value = [
                    {"id": i, "caption": f"Post {i}"} for i in range(100)
                ]
                mock_db.get_telegram_messages.return_value = []
                mock_get_db.return_value = mock_db

                result = runner.invoke(
                    cli,
                    ["db", "export", str(output_file), "--limit", "10"]
                )

                assert result.exit_code == 0
                # Database method should be called with limit
                mock_db.get_instagram_posts.assert_called_with(limit=10)

    def test_db_export_handles_empty_data(self, tmp_path: Path) -> None:
        """Test exporting empty database."""
        output_file = tmp_path / "empty_export.json"

        runner = CliRunner()

        with patch("backend.postparse.cli.db.load_config") as mock_load:
            with patch("backend.postparse.cli.db.get_database") as mock_get_db:
                mock_config = MagicMock()
                mock_load.return_value = mock_config

                mock_db = MagicMock()
                mock_db.get_instagram_posts.return_value = []
                mock_db.get_telegram_messages.return_value = []
                mock_get_db.return_value = mock_db

                result = runner.invoke(
                    cli,
                    ["db", "export", str(output_file)]
                )

                assert result.exit_code == 0
                assert output_file.exists()

    def test_db_export_handles_write_error(self, tmp_path: Path) -> None:
        """Test export handles file write errors."""
        # Use a path that will cause write error (e.g., read-only)
        output_file = tmp_path / "readonly" / "export.json"

        runner = CliRunner()

        with patch("backend.postparse.cli.db.load_config") as mock_load:
            with patch("backend.postparse.cli.db.get_database") as mock_get_db:
                mock_config = MagicMock()
                mock_load.return_value = mock_config

                mock_db = MagicMock()
                mock_db.get_instagram_posts.return_value = [{"id": 1}]
                mock_db.get_telegram_messages.return_value = []
                mock_get_db.return_value = mock_db

                result = runner.invoke(
                    cli,
                    ["db", "export", str(output_file)]
                )

                # Should handle error
                assert result.exit_code != 0


class TestDbCommandHelp:
    """Test db command help output."""

    def test_db_help_displays_subcommands(self) -> None:
        """Test that db --help shows available subcommands."""
        runner = CliRunner()
        result = runner.invoke(cli, ["db", "--help"])

        assert result.exit_code == 0
        output_lower = result.output.lower()
        assert "stats" in output_lower
        assert "export" in output_lower

    def test_db_stats_help(self) -> None:
        """Test db stats --help displays help text."""
        runner = CliRunner()
        result = runner.invoke(cli, ["db", "stats", "--help"])

        assert result.exit_code == 0
        assert "stats" in result.output.lower()
        assert "detailed" in result.output.lower()

    def test_db_export_help(self) -> None:
        """Test db export --help displays help text."""
        runner = CliRunner()
        result = runner.invoke(cli, ["db", "export", "--help"])

        assert result.exit_code == 0
        output_lower = result.output.lower()
        assert "export" in output_lower
        assert "format" in output_lower
        assert "json" in output_lower or "csv" in output_lower


class TestStatsAlias:
    """Test stats command as top-level alias."""

    def test_stats_alias_works(self) -> None:
        """Test that 'postparse stats' works as alias for 'postparse db stats'."""
        runner = CliRunner()

        with patch("backend.postparse.cli.db.load_config") as mock_load:
            with patch("backend.postparse.cli.db.get_database") as mock_get_db:
                mock_config = MagicMock()
                mock_config.get.return_value = "data/test.db"
                mock_load.return_value = mock_config

                mock_db = MagicMock()
                mock_db.get_instagram_posts.return_value = []
                mock_db.get_telegram_messages.return_value = []
                mock_get_db.return_value = mock_db

                result = runner.invoke(cli, ["stats"])

                # Should work same as db stats
                assert result.exit_code == 0

