"""
Unit tests for CLI utility functions.

This module tests the helper functions in the CLI utils module, including
console output, config loading, schema v2 database access and async operations.
"""

from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List
from unittest.mock import MagicMock, Mock, patch

import pytest
from rich.console import Console

from postparse.cli.utils import (
    config_path_from_ctx,
    emit_json,
    legacy_db_key_warning,
    open_database,
    resolve_db_path,
    create_progress,
    get_console,
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
        with patch("postparse.cli.utils.get_console") as mock_console:
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
        with patch("postparse.cli.utils.get_console") as mock_console:
            mock_console_instance = MagicMock()
            mock_console.return_value = mock_console_instance

            print_error("Test error message")

            mock_console_instance.print.assert_called_once()
            call_args = mock_console_instance.print.call_args
            assert "Test error message" in call_args[0][0]
            assert "red" in str(call_args).lower()

    def test_print_warning_outputs_correctly(self) -> None:
        """Test that print_warning outputs formatted warning message."""
        with patch("postparse.cli.utils.get_console") as mock_console:
            mock_console_instance = MagicMock()
            mock_console.return_value = mock_console_instance

            print_warning("Test warning message")

            mock_console_instance.print.assert_called_once()
            call_args = mock_console_instance.print.call_args
            assert "Test warning message" in call_args[0][0]
            assert "yellow" in str(call_args).lower()

    def test_print_info_outputs_correctly(self) -> None:
        """Test that print_info outputs formatted info message."""
        with patch("postparse.cli.utils.get_console") as mock_console:
            mock_console_instance = MagicMock()
            mock_console.return_value = mock_console_instance

            print_info("Test info message")

            mock_console_instance.print.assert_called_once()
            call_args = mock_console_instance.print.call_args
            assert "Test info message" in call_args[0][0]
            assert "cyan" in str(call_args).lower()

    def test_print_panel_creates_panel(self) -> None:
        """Test that print_panel creates and displays a panel."""
        with patch("postparse.cli.utils.get_console") as mock_console:
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

        with patch("postparse.cli.utils.get_console") as mock_console:
            mock_console_instance = MagicMock()
            mock_console.return_value = mock_console_instance

            print_table(test_data, title="Test Table")

            mock_console_instance.print.assert_called_once()

    def test_print_table_with_empty_data(self) -> None:
        """Test that print_table handles empty data gracefully."""
        with patch("postparse.cli.utils.get_console") as mock_console:
            with patch("postparse.cli.utils.print_warning") as mock_warning:
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

        with patch("postparse.cli.utils.ConfigManager") as mock_config_manager:
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

        with patch("postparse.cli.utils.ConfigManager") as mock_config_manager:
            mock_config_instance = MagicMock()
            mock_config_manager.return_value = mock_config_instance

            result = load_config()

            assert result is mock_config_instance


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



class TestDatabaseHelpers:
    """Schema v2 database helpers (``--db`` / ``Settings.db_path``)."""

    def test_config_path_from_ctx(self) -> None:
        assert config_path_from_ctx(None) is None
        assert config_path_from_ctx(Mock(obj={"config": "c.toml"})) == "c.toml"

    def test_resolve_db_path_prefers_explicit_value(self, tmp_path: Path) -> None:
        assert resolve_db_path(None, str(tmp_path / "x.db")) == (tmp_path / "x.db").resolve()

    def test_resolve_db_path_uses_settings_not_legacy_key(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        from postparse.config import clear_settings_cache

        clear_settings_cache()
        path = resolve_db_path(Mock(obj={}))
        # The test config only has the v1 key default_db_path = data/social_media.db.
        assert path.name == "postparse.db"
        monkeypatch.setenv("POSTPARSE_DB_PATH", str(tmp_path / "env.db"))
        clear_settings_cache()
        assert resolve_db_path(Mock(obj={})) == tmp_path / "env.db"
        clear_settings_cache()

    def test_open_database_requires_existing_file(self, tmp_path: Path) -> None:
        import click

        with pytest.raises(click.ClickException, match="Database not found"):
            open_database(None, str(tmp_path / "missing.db"))
        assert not (tmp_path / "missing.db").exists()

    def test_open_database_rejects_old_schema(self, tmp_path: Path) -> None:
        import sqlite3

        import click

        path = tmp_path / "v0.db"
        sqlite3.connect(path).close()
        with pytest.raises(click.ClickException, match="db migrate"):
            open_database(None, str(path))

    def test_open_database_does_not_migrate(self, v2_db: tuple[Path, dict[str, int]]) -> None:
        path, _ = v2_db
        db = open_database(None, str(path))
        assert db._migrate is False
        with db.read() as conn:
            assert conn.execute("SELECT count(*) FROM items").fetchone()[0] == 4

    def test_legacy_db_key_warning(self, tmp_path: Path) -> None:
        legacy = tmp_path / "legacy.toml"
        legacy.write_text('[database]\ndefault_db_path = "data/social_media.db"\n')
        warning = legacy_db_key_warning(str(legacy))
        assert warning is not None and "migrate-v1" in warning
        new = tmp_path / "new.toml"
        new.write_text('[database]\ndefault_db_path = "a.db"\ndb_path = "b.db"\n')
        assert legacy_db_key_warning(str(new)) is None
        assert legacy_db_key_warning(str(tmp_path / "missing.toml")) is None

    def test_emit_json(self, capsys: pytest.CaptureFixture) -> None:
        emit_json({"a": "ä", "n": 1})
        assert '"a": "ä"' in capsys.readouterr().out
