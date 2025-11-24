"""
Unit tests for CLI extract commands.

This module tests data extraction commands for Telegram and Instagram,
including credential validation and extraction logic.
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from click.testing import CliRunner

from postparse.cli.main import cli


class TestExtractTelegram:
    """Test extract telegram command."""

    def test_extract_telegram_requires_credentials(self) -> None:
        """
        Test that extract telegram validates API credentials.

        Verifies proper error handling when required credentials are missing.
        """
        runner = CliRunner()

        with patch("postparse.cli.extract.validate_credentials") as mock_validate:
            # Simulate missing credentials
            mock_validate.return_value = ["api_id", "api_hash"]

            result = runner.invoke(
                cli,
                ["extract", "telegram", "--api-id", "", "--api-hash", ""],
            )

            # Should handle missing credentials
            assert result.exit_code != 0 or "missing" in result.output.lower()

    def test_extract_telegram_with_valid_credentials(self) -> None:
        """Test extract telegram with valid credentials and successful extraction."""
        runner = CliRunner()

        with patch("postparse.cli.extract.load_config") as mock_load:
            with patch("postparse.cli.extract.get_database") as mock_get_db:
                with patch("postparse.services.parsers.telegram.telegram_parser.TelegramParser") as mock_parser_class:
                    with patch("postparse.cli.extract.run_async") as mock_run_async:
                        mock_config = MagicMock()
                        mock_load.return_value = mock_config

                        mock_db = MagicMock()
                        mock_get_db.return_value = mock_db

                        # Mock parser with async context manager
                        mock_parser = MagicMock()
                        mock_parser.__aenter__ = AsyncMock(return_value=mock_parser)
                        mock_parser.__aexit__ = AsyncMock(return_value=None)
                        mock_parser.save_messages_to_db = AsyncMock(return_value=10)
                        mock_parser_class.return_value = mock_parser

                        # Mock async result
                        mock_run_async.return_value = 10

                        result = runner.invoke(
                            cli,
                            [
                                "extract",
                                "telegram",
                                "--api-id",
                                "12345",
                                "--api-hash",
                                "abc123",
                            ],
                        )

                        assert result.exit_code == 0
                        # Should show extraction summary
                        assert "10" in result.output or "saved" in result.output.lower()

    def test_extract_telegram_with_limit(self) -> None:
        """Test extract telegram with message limit."""
        runner = CliRunner()

        with patch("postparse.cli.extract.load_config") as mock_load:
            with patch("postparse.cli.extract.get_database") as mock_get_db:
                with patch("postparse.services.parsers.telegram.telegram_parser.TelegramParser") as mock_parser_class:
                    with patch("postparse.cli.extract.run_async") as mock_run_async:
                        mock_config = MagicMock()
                        mock_load.return_value = mock_config

                        mock_db = MagicMock()
                        mock_get_db.return_value = mock_db

                        mock_parser = MagicMock()
                        mock_parser.__aenter__ = AsyncMock(return_value=mock_parser)
                        mock_parser.__aexit__ = AsyncMock(return_value=None)
                        mock_parser.save_messages_to_db = AsyncMock(return_value=5)
                        mock_parser_class.return_value = mock_parser

                        mock_run_async.return_value = 5

                        result = runner.invoke(
                            cli,
                            [
                                "extract",
                                "telegram",
                                "--api-id",
                                "12345",
                                "--api-hash",
                                "abc123",
                                "--limit",
                                "5",
                            ],
                        )

                        assert result.exit_code == 0

    def test_extract_telegram_with_force_flag(self) -> None:
        """Test extract telegram with --force flag for re-fetching."""
        runner = CliRunner()

        with patch("postparse.cli.extract.load_config") as mock_load:
            with patch("postparse.cli.extract.get_database") as mock_get_db:
                with patch("postparse.services.parsers.telegram.telegram_parser.TelegramParser") as mock_parser_class:
                    with patch("postparse.cli.extract.run_async") as mock_run_async:
                        mock_config = MagicMock()
                        mock_load.return_value = mock_config

                        mock_db = MagicMock()
                        mock_get_db.return_value = mock_db

                        mock_parser = MagicMock()
                        mock_parser.__aenter__ = AsyncMock(return_value=mock_parser)
                        mock_parser.__aexit__ = AsyncMock(return_value=None)
                        mock_parser.save_messages_to_db = AsyncMock(return_value=20)
                        mock_parser_class.return_value = mock_parser

                        mock_run_async.return_value = 20

                        result = runner.invoke(
                            cli,
                            [
                                "extract",
                                "telegram",
                                "--api-id",
                                "12345",
                                "--api-hash",
                                "abc123",
                                "--force",
                            ],
                        )

                        assert result.exit_code == 0

    def test_extract_telegram_handles_connection_error(self) -> None:
        """Test that extract telegram handles connection errors gracefully."""
        runner = CliRunner()

        with patch("postparse.cli.extract.load_config") as mock_load:
            with patch("postparse.cli.extract.get_database") as mock_get_db:
                with patch("postparse.services.parsers.telegram.telegram_parser.TelegramParser") as mock_parser:
                    mock_config = MagicMock()
                    mock_load.return_value = mock_config

                    mock_db = MagicMock()
                    mock_get_db.return_value = mock_db

                    mock_parser.side_effect = Exception("Connection failed")

                    result = runner.invoke(
                        cli,
                        [
                            "extract",
                            "telegram",
                            "--api-id",
                            "12345",
                            "--api-hash",
                            "abc123",
                        ],
                    )

                    assert result.exit_code != 0
                    assert "error" in result.output.lower() or "failed" in result.output.lower()

    def test_extract_telegram_uses_env_vars(self) -> None:
        """Test that extract telegram uses environment variables for credentials."""
        runner = CliRunner()

        with patch("postparse.cli.extract.load_config") as mock_load:
            with patch("postparse.cli.extract.get_database") as mock_get_db:
                with patch("postparse.services.parsers.telegram.telegram_parser.TelegramParser") as mock_parser_class:
                    with patch("postparse.cli.extract.run_async") as mock_run_async:
                        mock_config = MagicMock()
                        mock_load.return_value = mock_config

                        mock_db = MagicMock()
                        mock_get_db.return_value = mock_db

                        mock_parser = MagicMock()
                        mock_parser.__aenter__ = AsyncMock(return_value=mock_parser)
                        mock_parser.__aexit__ = AsyncMock(return_value=None)
                        mock_parser.save_messages_to_db = AsyncMock(return_value=5)
                        mock_parser_class.return_value = mock_parser

                        mock_run_async.return_value = 5

                        # Set env vars
                        result = runner.invoke(
                            cli,
                            ["extract", "telegram"],
                            env={
                                "TELEGRAM_API_ID": "12345",
                                "TELEGRAM_API_HASH": "abc123",
                            },
                        )

                        assert result.exit_code == 0


class TestExtractInstagram:
    """Test extract instagram command."""

    def test_extract_instagram_requires_credentials(self) -> None:
        """Test that extract instagram validates username and password."""
        runner = CliRunner()

        with patch("postparse.cli.extract.validate_credentials") as mock_validate:
            # Simulate missing credentials
            mock_validate.return_value = ["username", "password"]

            result = runner.invoke(
                cli,
                ["extract", "instagram", "--username", "", "--password", ""],
            )

            # Should handle missing credentials
            assert result.exit_code != 0 or "missing" in result.output.lower()

    def test_extract_instagram_with_valid_credentials(self) -> None:
        """Test extract instagram with valid credentials."""
        runner = CliRunner()

        with patch("postparse.cli.extract.load_config") as mock_load:
            with patch("postparse.cli.extract.get_database") as mock_get_db:
                with patch("postparse.services.parsers.instagram.instagram_parser.InstaloaderParser") as mock_parser_class:
                    mock_config = MagicMock()
                    mock_load.return_value = mock_config

                    mock_db = MagicMock()
                    mock_get_db.return_value = mock_db

                    mock_parser = MagicMock()
                    mock_parser.save_posts_to_db.return_value = 15
                    mock_parser_class.return_value = mock_parser

                    result = runner.invoke(
                        cli,
                        [
                            "extract",
                            "instagram",
                            "--username",
                            "testuser",
                            "--password",
                            "testpass",
                        ],
                    )

                    assert result.exit_code == 0
                    # Should show extraction summary
                    assert "15" in result.output or "saved" in result.output.lower()

    def test_extract_instagram_with_limit(self) -> None:
        """Test extract instagram with post limit."""
        runner = CliRunner()

        with patch("postparse.cli.extract.load_config") as mock_load:
            with patch("postparse.cli.extract.get_database") as mock_get_db:
                with patch("postparse.services.parsers.instagram.instagram_parser.InstaloaderParser") as mock_parser_class:
                    mock_config = MagicMock()
                    mock_load.return_value = mock_config

                    mock_db = MagicMock()
                    mock_get_db.return_value = mock_db

                    mock_parser = MagicMock()
                    mock_parser.save_posts_to_db.return_value = 10
                    mock_parser_class.return_value = mock_parser

                    result = runner.invoke(
                        cli,
                        [
                            "extract",
                            "instagram",
                            "--username",
                            "testuser",
                            "--password",
                            "testpass",
                            "--limit",
                            "10",
                        ],
                    )

                    assert result.exit_code == 0

    def test_extract_instagram_with_force_flag(self) -> None:
        """Test extract instagram with --force flag."""
        runner = CliRunner()

        with patch("postparse.cli.extract.load_config") as mock_load:
            with patch("postparse.cli.extract.get_database") as mock_get_db:
                with patch("postparse.services.parsers.instagram.instagram_parser.InstaloaderParser") as mock_parser_class:
                    mock_config = MagicMock()
                    mock_load.return_value = mock_config

                    mock_db = MagicMock()
                    mock_get_db.return_value = mock_db

                    mock_parser = MagicMock()
                    mock_parser.save_posts_to_db.return_value = 25
                    mock_parser_class.return_value = mock_parser

                    result = runner.invoke(
                        cli,
                        [
                            "extract",
                            "instagram",
                            "--username",
                            "testuser",
                            "--password",
                            "testpass",
                            "--force",
                        ],
                    )

                    assert result.exit_code == 0

    def test_extract_instagram_handles_login_error(self) -> None:
        """Test that extract instagram handles login errors."""
        runner = CliRunner()

        with patch("postparse.cli.extract.load_config") as mock_load:
            with patch("postparse.cli.extract.get_database") as mock_get_db:
                with patch("postparse.services.parsers.instagram.instagram_parser.InstaloaderParser") as mock_parser:
                    mock_config = MagicMock()
                    mock_load.return_value = mock_config

                    mock_db = MagicMock()
                    mock_get_db.return_value = mock_db

                    mock_parser.side_effect = Exception("Login failed")

                    result = runner.invoke(
                        cli,
                        [
                            "extract",
                            "instagram",
                            "--username",
                            "testuser",
                            "--password",
                            "wrongpass",
                        ],
                    )

                    assert result.exit_code != 0

    def test_extract_instagram_uses_env_vars(self) -> None:
        """Test that extract instagram uses environment variables."""
        runner = CliRunner()

        with patch("postparse.cli.extract.load_config") as mock_load:
            with patch("postparse.cli.extract.get_database") as mock_get_db:
                with patch("postparse.services.parsers.instagram.instagram_parser.InstaloaderParser") as mock_parser_class:
                    mock_config = MagicMock()
                    mock_load.return_value = mock_config

                    mock_db = MagicMock()
                    mock_get_db.return_value = mock_db

                    mock_parser = MagicMock()
                    mock_parser.save_posts_to_db.return_value = 8
                    mock_parser_class.return_value = mock_parser

                    result = runner.invoke(
                        cli,
                        ["extract", "instagram"],
                        env={
                            "INSTAGRAM_USERNAME": "testuser",
                            "INSTAGRAM_PASSWORD": "testpass",
                        },
                    )

                    assert result.exit_code == 0


class TestExtractHelp:
    """Test extract command help output."""

    def test_extract_help_displays_subcommands(self) -> None:
        """Test that extract --help shows available subcommands."""
        runner = CliRunner()
        result = runner.invoke(cli, ["extract", "--help"])

        assert result.exit_code == 0
        output_lower = result.output.lower()
        assert "telegram" in output_lower
        assert "instagram" in output_lower

    def test_extract_telegram_help(self) -> None:
        """Test extract telegram --help displays help text."""
        runner = CliRunner()
        result = runner.invoke(cli, ["extract", "telegram", "--help"])

        assert result.exit_code == 0
        output_lower = result.output.lower()
        assert "telegram" in output_lower
        assert "api-id" in output_lower or "api_id" in output_lower
        assert "limit" in output_lower
        assert "force" in output_lower

    def test_extract_instagram_help(self) -> None:
        """Test extract instagram --help displays help text."""
        runner = CliRunner()
        result = runner.invoke(cli, ["extract", "instagram", "--help"])

        assert result.exit_code == 0
        output_lower = result.output.lower()
        assert "instagram" in output_lower
        assert "username" in output_lower
        assert "password" in output_lower
        assert "limit" in output_lower

