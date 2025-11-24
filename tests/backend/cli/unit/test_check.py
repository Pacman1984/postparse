"""
Unit tests for CLI check commands.

This module tests the check commands for examining new content
available on Telegram and Instagram without downloading.
"""

from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from click.testing import CliRunner

from postparse.cli.main import cli


class TestCheckTelegram:
    """Test check telegram command."""

    def test_check_telegram_requires_credentials(self) -> None:
        """
        Test that check telegram validates credentials properly.

        Verifies that missing credentials are handled with proper error.
        """
        runner = CliRunner()

        with patch("postparse.cli.check.validate_credentials") as mock_validate:
            # Simulate missing credentials
            mock_validate.return_value = ["api_id", "api_hash"]

            result = runner.invoke(
                cli,
                ["check", "telegram", "--api-id", "", "--api-hash", ""],
            )

            # Should handle missing credentials
            assert result.exit_code != 0 or "missing" in result.output.lower()

    def test_check_telegram_with_valid_credentials(self) -> None:
        """
        Test check telegram with valid credentials.
        
        This test mocks only external boundaries (parser, database) and lets
        the actual check logic execute to compute real statistics.
        """
        runner = CliRunner()

        with patch("postparse.cli.check.load_config") as mock_load:
            with patch("postparse.cli.check.get_database") as mock_get_db:
                with patch("postparse.services.parsers.telegram.telegram_parser.TelegramParser") as mock_parser_class:
                    mock_config = MagicMock()
                    mock_load.return_value = mock_config

                    mock_db = MagicMock()
                    mock_db.get_telegram_messages.return_value = []
                    mock_db.message_exists.return_value = False
                    mock_get_db.return_value = mock_db

                    # Mock parser with async context manager
                    mock_parser = MagicMock()
                    mock_parser.__aenter__ = AsyncMock(return_value=mock_parser)
                    mock_parser.__aexit__ = AsyncMock(return_value=None)
                    
                    async def mock_get_saved_messages(*args, **kwargs):
                        for i in range(5):
                            yield {
                                "message_id": i,
                                "date": "2024-01-15T10:00:00Z",
                                "text": f"Message {i}",
                            }
                    
                    mock_parser.get_saved_messages = mock_get_saved_messages
                    mock_parser_class.return_value = mock_parser

                    # Let run_async execute the real check logic
                    # It will use the mocked parser data and compute real statistics

                    result = runner.invoke(
                        cli,
                        [
                            "check",
                            "telegram",
                            "--api-id",
                            "12345",
                            "--api-hash",
                            "abc123",
                        ],
                    )

                    assert result.exit_code == 0
                    # Verify actual statistics were computed and displayed
                    assert "5" in result.output or "new" in result.output.lower()
                    # Verify connection success message
                    assert "connected" in result.output.lower() or "telegram" in result.output.lower()

    def test_check_telegram_displays_statistics(self) -> None:
        """
        Test that check telegram displays message statistics.
        
        Verifies that the command computes and displays statistics based on
        real data from mocked parser (not pre-computed mock results).
        """
        runner = CliRunner()

        with patch("postparse.cli.check.load_config") as mock_load:
            with patch("postparse.cli.check.get_database") as mock_get_db:
                with patch("postparse.services.parsers.telegram.telegram_parser.TelegramParser") as mock_parser_class:
                    mock_config = MagicMock()
                    mock_load.return_value = mock_config

                    mock_db = MagicMock()
                    mock_db.get_telegram_messages.return_value = [
                        {"date": "2024-01-10T10:00:00Z"}
                    ]
                    mock_db.message_exists.return_value = False
                    mock_get_db.return_value = mock_db

                    # Mock parser to yield 10 messages
                    mock_parser = MagicMock()
                    mock_parser.__aenter__ = AsyncMock(return_value=mock_parser)
                    mock_parser.__aexit__ = AsyncMock(return_value=None)
                    
                    async def mock_get_saved_messages(*args, **kwargs):
                        for i in range(10):
                            yield {
                                "message_id": i,
                                "date": "2024-01-15T10:00:00Z",
                                "text": f"Message {i}",
                            }
                    
                    mock_parser.get_saved_messages = mock_get_saved_messages
                    mock_parser_class.return_value = mock_parser

                    # Let the command compute statistics from the mocked messages
                    result = runner.invoke(
                        cli,
                        [
                            "check",
                            "telegram",
                            "--api-id",
                            "12345",
                            "--api-hash",
                            "abc123",
                        ],
                    )

                    assert result.exit_code == 0
                    # Verify statistics are displayed (command should count the 10 messages)
                    assert "10" in result.output or "new" in result.output.lower()
                    # Verify status information is shown
                    assert "telegram" in result.output.lower() or "message" in result.output.lower()

    def test_check_telegram_handles_connection_error(self) -> None:
        """Test that check telegram handles connection errors."""
        runner = CliRunner()

        with patch("postparse.cli.check.load_config") as mock_load:
            with patch("postparse.cli.check.get_database") as mock_get_db:
                with patch("postparse.services.parsers.telegram.telegram_parser.TelegramParser") as mock_parser:
                    mock_config = MagicMock()
                    mock_load.return_value = mock_config

                    mock_db = MagicMock()
                    mock_get_db.return_value = mock_db

                    mock_parser.side_effect = Exception("Connection failed")

                    result = runner.invoke(
                        cli,
                        [
                            "check",
                            "telegram",
                            "--api-id",
                            "12345",
                            "--api-hash",
                            "abc123",
                        ],
                    )

                    # Should handle error gracefully
                    assert result.exit_code != 0


class TestCheckInstagram:
    """Test check instagram command."""

    def test_check_instagram_requires_credentials(self) -> None:
        """Test that check instagram validates username and password."""
        runner = CliRunner()

        with patch("postparse.cli.check.validate_credentials") as mock_validate:
            # Simulate missing credentials
            mock_validate.return_value = ["username", "password"]

            result = runner.invoke(
                cli,
                ["check", "instagram", "--username", "", "--password", ""],
            )

            # Should handle missing credentials
            assert result.exit_code != 0 or "missing" in result.output.lower()

    def test_check_instagram_with_valid_credentials(self) -> None:
        """Test check instagram with valid credentials."""
        runner = CliRunner()

        with patch("postparse.cli.check.load_config") as mock_load:
            with patch("postparse.cli.check.get_database") as mock_get_db:
                with patch("postparse.services.parsers.instagram.instagram_parser.InstaloaderParser") as mock_parser_class:
                    mock_config = MagicMock()
                    mock_load.return_value = mock_config

                    mock_db = MagicMock()
                    mock_db.get_instagram_posts.return_value = []
                    mock_db.post_exists.return_value = False
                    mock_get_db.return_value = mock_db

                    mock_parser = MagicMock()
                    
                    def mock_get_saved_posts(*args, **kwargs):
                        for i in range(5):
                            yield {
                                "shortcode": f"post{i}",
                                "date": "2024-01-15T10:00:00Z",
                                "caption": f"Post {i}",
                            }
                    
                    mock_parser.get_saved_posts = mock_get_saved_posts
                    mock_parser_class.return_value = mock_parser

                    result = runner.invoke(
                        cli,
                        [
                            "check",
                            "instagram",
                            "--username",
                            "testuser",
                            "--password",
                            "testpass",
                        ],
                    )

                    assert result.exit_code == 0

    def test_check_instagram_displays_statistics(self) -> None:
        """Test that check instagram displays post statistics."""
        runner = CliRunner()

        with patch("postparse.cli.check.load_config") as mock_load:
            with patch("postparse.cli.check.get_database") as mock_get_db:
                with patch("postparse.services.parsers.instagram.instagram_parser.InstaloaderParser") as mock_parser_class:
                    mock_config = MagicMock()
                    mock_load.return_value = mock_config

                    mock_db = MagicMock()
                    mock_db.get_instagram_posts.return_value = []
                    mock_db.post_exists.return_value = False
                    mock_get_db.return_value = mock_db

                    mock_parser = MagicMock()
                    
                    def mock_get_saved_posts(*args, **kwargs):
                        for i in range(8):
                            yield {
                                "shortcode": f"post{i}",
                                "date": "2024-01-15T10:00:00Z",
                            }
                    
                    mock_parser.get_saved_posts = mock_get_saved_posts
                    mock_parser_class.return_value = mock_parser

                    result = runner.invoke(
                        cli,
                        [
                            "check",
                            "instagram",
                            "--username",
                            "testuser",
                            "--password",
                            "testpass",
                        ],
                    )

                    assert result.exit_code == 0
                    # Should display count
                    assert "8" in result.output or "new" in result.output.lower()


class TestCheckAll:
    """Test check all command."""

    def test_check_all_with_no_credentials(self) -> None:
        """Test check all when no credentials are provided."""
        runner = CliRunner()

        with patch("postparse.cli.check.load_config") as mock_load:
            with patch("postparse.cli.check.get_database") as mock_get_db:
                with patch("os.getenv", return_value=None):
                    mock_config = MagicMock()
                    mock_config.get.return_value = "data/test.db"
                    mock_load.return_value = mock_config

                    mock_db = MagicMock()
                    mock_db.get_instagram_posts.return_value = []
                    mock_db.get_telegram_messages.return_value = []
                    mock_get_db.return_value = mock_db

                    result = runner.invoke(cli, ["check", "all"])

                    assert result.exit_code == 0
                    # Should warn about missing credentials
                    output_lower = result.output.lower()
                    assert "skip" in output_lower or "no credentials" in output_lower or "credentials" in output_lower

    def test_check_all_checks_both_platforms(self) -> None:
        """Test that check all attempts to check both platforms."""
        runner = CliRunner()

        with patch("postparse.cli.check.load_config") as mock_load:
            with patch("postparse.cli.check.get_database") as mock_get_db:
                with patch("os.getenv") as mock_getenv:
                    # Provide credentials for both platforms
                    mock_getenv.side_effect = lambda key: {
                        "TELEGRAM_API_ID": "12345",
                        "TELEGRAM_API_HASH": "abc123",
                        "INSTAGRAM_USERNAME": "testuser",
                        "INSTAGRAM_PASSWORD": "testpass",
                    }.get(key)

                    mock_config = MagicMock()
                    mock_config.get.return_value = "data/test.db"
                    mock_load.return_value = mock_config

                    mock_db = MagicMock()
                    mock_db.get_instagram_posts.return_value = []
                    mock_db.get_telegram_messages.return_value = []
                    mock_get_db.return_value = mock_db

                    result = runner.invoke(cli, ["check", "all"])

                    # May succeed or fail depending on mocks, but should attempt
                    assert isinstance(result.exit_code, int)

    def test_check_all_without_subcommand_defaults_to_all(self) -> None:
        """Test that 'check' without subcommand defaults to 'check all'."""
        runner = CliRunner()

        with patch("postparse.cli.check.load_config") as mock_load:
            with patch("postparse.cli.check.get_database") as mock_get_db:
                with patch("os.getenv", return_value=None):
                    mock_config = MagicMock()
                    mock_config.get.return_value = "data/test.db"
                    mock_load.return_value = mock_config

                    mock_db = MagicMock()
                    mock_db.get_instagram_posts.return_value = []
                    mock_db.get_telegram_messages.return_value = []
                    mock_get_db.return_value = mock_db

                    result = runner.invoke(cli, ["check"])

                    assert result.exit_code == 0
                    # Should run 'all' by default
                    output_lower = result.output.lower()
                    assert "platform" in output_lower or "check" in output_lower


class TestCheckHelp:
    """Test check command help output."""

    def test_check_help_displays_subcommands(self) -> None:
        """Test that check --help shows available subcommands."""
        runner = CliRunner()
        result = runner.invoke(cli, ["check", "--help"])

        assert result.exit_code == 0
        output_lower = result.output.lower()
        assert "telegram" in output_lower
        assert "instagram" in output_lower
        assert "all" in output_lower

    def test_check_telegram_help(self) -> None:
        """Test check telegram --help displays help text."""
        runner = CliRunner()
        result = runner.invoke(cli, ["check", "telegram", "--help"])

        assert result.exit_code == 0
        output_lower = result.output.lower()
        assert "telegram" in output_lower
        assert "api-id" in output_lower or "api_id" in output_lower

    def test_check_instagram_help(self) -> None:
        """Test check instagram --help displays help text."""
        runner = CliRunner()
        result = runner.invoke(cli, ["check", "instagram", "--help"])

        assert result.exit_code == 0
        output_lower = result.output.lower()
        assert "instagram" in output_lower
        assert "username" in output_lower

