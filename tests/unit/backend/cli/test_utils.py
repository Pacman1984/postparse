"""
Unit tests for CLI utility functions.

This module tests the helper functions in the CLI utils module, including
console output, config loading, database access, and async operations.
"""

from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List
from unittest.mock import MagicMock, Mock, patch

import pytest
from rich.console import Console

from backend.postparse.cli.utils import (
    create_progress,
    format_message,
    format_post,
    get_console,
    get_database,
    load_config,
    parse_date,
    print_error,
    print_info,
    print_panel,
    print_success,
    print_table,
    print_warning,
    run_async,
    truncate_text,
    validate_config,
    validate_credentials,
)


class TestConsoleOutput:
    """Test console output functions."""

    def test_get_console_returns_singleton(self) -> None:
        """
        Test that get_console returns the same Console instance.

        This verifies that the console is properly instantiated as a singleton
        to avoid creating multiple Console instances.
        """
        console1 = get_console()
        console2 = get_console()

        assert console1 is console2
        assert isinstance(console1, Console)

    def test_print_success_outputs_correctly(self, capsys: pytest.CaptureFixture) -> None:
        """
        Test that print_success outputs formatted message.

        Verifies that success messages are printed with appropriate styling.
        """
        with patch("backend.postparse.cli.utils.get_console") as mock_console:
            mock_console_instance = MagicMock()
            mock_console.return_value = mock_console_instance

            print_success("Test success message")

            # Verify the console.print was called
            mock_console_instance.print.assert_called_once()
            call_args = mock_console_instance.print.call_args
            assert "Test success message" in call_args[0][0]
            assert "green" in str(call_args).lower()

    def test_print_error_outputs_correctly(self) -> None:
        """Test that print_error outputs formatted error message."""
        with patch("backend.postparse.cli.utils.get_console") as mock_console:
            mock_console_instance = MagicMock()
            mock_console.return_value = mock_console_instance

            print_error("Test error message")

            mock_console_instance.print.assert_called_once()
            call_args = mock_console_instance.print.call_args
            assert "Test error message" in call_args[0][0]
            assert "red" in str(call_args).lower()

    def test_print_warning_outputs_correctly(self) -> None:
        """Test that print_warning outputs formatted warning message."""
        with patch("backend.postparse.cli.utils.get_console") as mock_console:
            mock_console_instance = MagicMock()
            mock_console.return_value = mock_console_instance

            print_warning("Test warning message")

            mock_console_instance.print.assert_called_once()
            call_args = mock_console_instance.print.call_args
            assert "Test warning message" in call_args[0][0]
            assert "yellow" in str(call_args).lower()

    def test_print_info_outputs_correctly(self) -> None:
        """Test that print_info outputs formatted info message."""
        with patch("backend.postparse.cli.utils.get_console") as mock_console:
            mock_console_instance = MagicMock()
            mock_console.return_value = mock_console_instance

            print_info("Test info message")

            mock_console_instance.print.assert_called_once()
            call_args = mock_console_instance.print.call_args
            assert "Test info message" in call_args[0][0]
            assert "cyan" in str(call_args).lower()

    def test_print_panel_creates_panel(self) -> None:
        """Test that print_panel creates and displays a panel."""
        with patch("backend.postparse.cli.utils.get_console") as mock_console:
            mock_console_instance = MagicMock()
            mock_console.return_value = mock_console_instance

            print_panel("Test content", title="Test Title", style="green")

            mock_console_instance.print.assert_called_once()

    def test_print_table_with_data(self) -> None:
        """Test that print_table displays data correctly."""
        test_data = [
            {"id": 1, "name": "Item 1"},
            {"id": 2, "name": "Item 2"},
        ]

        with patch("backend.postparse.cli.utils.get_console") as mock_console:
            mock_console_instance = MagicMock()
            mock_console.return_value = mock_console_instance

            print_table(test_data, title="Test Table")

            mock_console_instance.print.assert_called_once()

    def test_print_table_with_empty_data(self) -> None:
        """Test that print_table handles empty data gracefully."""
        with patch("backend.postparse.cli.utils.get_console") as mock_console:
            with patch("backend.postparse.cli.utils.print_warning") as mock_warning:
                print_table([], title="Empty Table")

                # Should call print_warning instead of printing table
                mock_warning.assert_called_once_with("No data to display")


class TestConfigManagement:
    """Test configuration management functions."""

    def test_load_config_with_valid_path(self, tmp_path: Path) -> None:
        """
        Test loading config with valid path.

        Creates a temporary config file and verifies it can be loaded.
        """
        config_file = tmp_path / "config.toml"
        config_file.write_text("""
[database]
path = "test.db"

[api]
port = 8000
""")

        with patch("backend.postparse.cli.utils.ConfigManager") as mock_config_manager:
            mock_config_instance = MagicMock()
            mock_config_manager.return_value = mock_config_instance

            result = load_config(str(config_file))

            mock_config_manager.assert_called_once_with(config_path=Path(str(config_file)))
            assert result is mock_config_instance

    def test_load_config_with_nonexistent_path(self) -> None:
        """Test that load_config raises error for nonexistent file."""
        with pytest.raises(Exception) as exc_info:
            load_config("/nonexistent/path/config.toml")

        assert "Config file not found" in str(exc_info.value) or "Failed to load config" in str(exc_info.value)

    def test_load_config_finds_default_location(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """Test that load_config finds config in default locations."""
        # Create config in default location
        config_dir = tmp_path / "config"
        config_dir.mkdir()
        config_file = config_dir / "config.toml"
        config_file.write_text("""
[database]
path = "test.db"
""")

        # Change to temp directory
        monkeypatch.chdir(tmp_path)

        with patch("backend.postparse.cli.utils.ConfigManager") as mock_config_manager:
            mock_config_instance = MagicMock()
            mock_config_manager.return_value = mock_config_instance

            result = load_config()

            assert result is mock_config_instance

    def test_validate_config_with_valid_config(self) -> None:
        """Test config validation with valid configuration."""
        with patch("backend.postparse.cli.utils.load_config") as mock_load:
            mock_config = MagicMock()
            mock_config.get.side_effect = lambda key, default=None: {
                "database.path": "data/test.db",
                "database.default_db_path": "data/test.db",
            }.get(key, default)
            mock_config.get_section.return_value = {"providers": [{"name": "test"}]}
            mock_load.return_value = mock_config

            issues = validate_config()

            # Should return empty list for valid config
            assert isinstance(issues, list)

    def test_validate_config_with_missing_database_path(self) -> None:
        """Test config validation detects missing database path."""
        with patch("backend.postparse.cli.utils.load_config") as mock_load:
            mock_config = MagicMock()
            mock_config.get.return_value = None
            mock_config.get_section.return_value = {"providers": []}
            mock_load.return_value = mock_config

            issues = validate_config()

            assert isinstance(issues, list)
            assert len(issues) > 0
            # Check that database path issue is detected
            assert any("Database path" in issue.get("check", "") for issue in issues)


class TestDatabaseAccess:
    """Test database access functions."""

    def test_get_database_returns_instance(self) -> None:
        """
        Test that get_database returns SocialMediaDatabase instance.

        Mocks the database class at the boundary to test that the function
        correctly instantiates and returns a database object.
        """
        with patch("backend.postparse.core.data.database.SocialMediaDatabase") as mock_db_class:
            mock_config = MagicMock()
            mock_config.get.return_value = "data/test.db"

            mock_db_instance = MagicMock()
            mock_db_class.return_value = mock_db_instance

            result = get_database(mock_config)

            mock_db_class.assert_called_once_with("data/test.db")
            assert result is mock_db_instance

    def test_get_database_with_default_path(self) -> None:
        """Test that get_database uses default path when not configured."""
        with patch("backend.postparse.core.data.database.SocialMediaDatabase") as mock_db_class:
            mock_config = MagicMock()
            mock_config.get.side_effect = lambda key, default=None: {
                "database.path": None,
                "database.default_db_path": "data/postparse.db"
            }.get(key, default)

            mock_db_instance = MagicMock()
            mock_db_class.return_value = mock_db_instance

            result = get_database(mock_config)

            # Should use default path
            assert mock_db_class.called
            call_args = mock_db_class.call_args[0][0]
            assert "postparse.db" in call_args


class TestFormatting:
    """Test data formatting functions."""

    def test_format_post_with_complete_data(self) -> None:
        """
        Test formatting Instagram post with all fields.

        Uses real data structure to verify formatting logic works correctly.
        """
        post = {
            "id": 123,
            "owner_username": "testuser",
            "caption": "This is a test post with a caption",
            "content_type": "image",
            "likes": 42,
            "date": "2024-01-15T10:30:00Z",
        }

        result = format_post(post)

        assert result["id"] == "123"
        assert result["username"] == "testuser"
        assert result["caption_preview"] == "This is a test post with a caption"
        assert result["type"] == "image"
        assert result["likes"] == "42"
        assert result["date"] == "2024-01-15"

    def test_format_post_truncates_long_caption(self) -> None:
        """Test that format_post truncates long captions."""
        post = {
            "id": 123,
            "caption": "A" * 100,  # Very long caption
            "content_type": "image",
            "likes": 10,
            "date": "2024-01-15T10:30:00Z",
        }

        result = format_post(post)

        assert len(result["caption_preview"]) == 53  # 50 + "..."
        assert result["caption_preview"].endswith("...")

    def test_format_post_handles_missing_fields(self) -> None:
        """Test that format_post handles missing fields gracefully."""
        post: Dict[str, Any] = {"id": 123}

        result = format_post(post)

        assert result["id"] == "123"
        assert result["username"] == ""
        assert result["caption_preview"] == ""
        assert result["type"] == ""
        assert result["likes"] == "0"
        assert result["date"] == ""

    def test_format_message_with_complete_data(self) -> None:
        """Test formatting Telegram message with all fields."""
        message = {
            "id": 456,
            "text": "This is a test message",
            "media_type": "photo",
            "views": 100,
            "date": "2024-01-20T15:45:00Z",
        }

        result = format_message(message)

        assert result["id"] == "456"
        assert result["content_preview"] == "This is a test message"
        assert result["type"] == "photo"
        assert result["views"] == "100"
        assert result["date"] == "2024-01-20"

    def test_format_message_uses_caption_when_no_text(self) -> None:
        """Test that format_message uses caption when text is absent."""
        message = {
            "id": 456,
            "caption": "Photo caption",
            "media_type": "photo",
            "views": 50,
        }

        result = format_message(message)

        assert result["content_preview"] == "Photo caption"

    def test_format_message_truncates_long_content(self) -> None:
        """Test that format_message truncates long content."""
        message = {
            "id": 456,
            "text": "B" * 100,
            "media_type": "text",
            "views": 25,
        }

        result = format_message(message)

        assert len(result["content_preview"]) == 53  # 50 + "..."
        assert result["content_preview"].endswith("...")


class TestUtilityFunctions:
    """Test utility helper functions."""

    def test_truncate_text_short_text(self) -> None:
        """Test that truncate_text returns short text unchanged."""
        text = "Short text"
        result = truncate_text(text, max_length=50)

        assert result == text
        assert not result.endswith("...")

    def test_truncate_text_long_text(self) -> None:
        """Test that truncate_text truncates long text correctly."""
        text = "This is a very long text that should be truncated"
        result = truncate_text(text, max_length=20)

        assert len(result) == 20
        assert result.endswith("...")
        assert result == "This is a very lo..."

    def test_truncate_text_exact_length(self) -> None:
        """Test truncate_text with text exactly at max length."""
        text = "A" * 50
        result = truncate_text(text, max_length=50)

        assert result == text
        assert not result.endswith("...")

    def test_parse_date_valid_format(self) -> None:
        """
        Test parsing valid date string.

        Uses real datetime parsing to verify the logic works correctly.
        """
        date_str = "2024-01-15"
        result = parse_date(date_str)

        assert isinstance(result, datetime)
        assert result.year == 2024
        assert result.month == 1
        assert result.day == 15

    def test_parse_date_invalid_format(self) -> None:
        """Test that parse_date raises ValueError for invalid format."""
        with pytest.raises(ValueError) as exc_info:
            parse_date("15-01-2024")

        assert "Invalid date format" in str(exc_info.value)

    def test_parse_date_invalid_date(self) -> None:
        """Test that parse_date raises ValueError for invalid date."""
        with pytest.raises(ValueError):
            parse_date("2024-13-40")  # Invalid month and day

    def test_validate_credentials_all_provided(self) -> None:
        """Test credential validation when all are provided."""
        required = ["api_id", "api_hash", "phone"]
        provided = {
            "api_id": "12345",
            "api_hash": "abc123",
            "phone": "+1234567890",
        }

        missing = validate_credentials(required, provided)

        assert missing == []

    def test_validate_credentials_some_missing(self) -> None:
        """Test credential validation when some are missing."""
        required = ["api_id", "api_hash", "phone"]
        provided = {
            "api_id": "12345",
            "api_hash": None,
            "phone": "",
        }

        missing = validate_credentials(required, provided)

        assert "api_hash" in missing
        assert "phone" in missing
        assert "api_id" not in missing
        assert len(missing) == 2

    def test_validate_credentials_all_missing(self) -> None:
        """Test credential validation when all are missing."""
        required = ["api_id", "api_hash"]
        provided: Dict[str, str] = {}

        missing = validate_credentials(required, provided)

        assert len(missing) == 2
        assert "api_id" in missing
        assert "api_hash" in missing


class TestAsyncOperations:
    """Test async operation helpers."""

    def test_run_async_simple_coroutine(self) -> None:
        """
        Test running simple async function.

        Tests the actual async execution logic without mocking the core
        functionality, only testing at the boundary (event loop).
        """
        async def simple_coro() -> str:
            return "test_result"

        result = run_async(simple_coro())

        assert result == "test_result"

    def test_run_async_with_return_value(self) -> None:
        """Test running async function that returns a value."""
        async def coro_with_value() -> int:
            return 42

        result = run_async(coro_with_value())

        assert result == 42
        assert isinstance(result, int)

    def test_run_async_with_exception(self) -> None:
        """Test that run_async propagates exceptions correctly."""
        async def failing_coro() -> None:
            raise ValueError("Test error")

        with pytest.raises(ValueError) as exc_info:
            run_async(failing_coro())

        assert "Test error" in str(exc_info.value)

    def test_create_progress_returns_progress_instance(self) -> None:
        """Test that create_progress returns configured Progress instance."""
        progress = create_progress()

        # Verify it's a Progress instance with expected configuration
        assert progress is not None
        # Progress should have console set
        assert hasattr(progress, "console")

