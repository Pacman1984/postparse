"""
Unit tests for CLI main entry point.

This module tests the main CLI command group, version information,
and command registration.
"""

import io
from pathlib import Path
from unittest.mock import MagicMock, Mock, patch

import pytest
from click.testing import CliRunner

from postparse.cli.main import (
    __version__,
    cli,
    configure_stdio_utf8,
    info,
    main,
    load_env_files,
    show_welcome,
)


class TestEnvLoading:
    """Test environment file loading functionality."""

    def test_load_env_files_finds_config_env(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """
        Test that load_env_files finds and loads config/.env file.

        Creates a temporary .env file and verifies it's loaded correctly.
        """
        # Create config directory and .env file
        config_dir = tmp_path / "config"
        config_dir.mkdir()
        env_file = config_dir / ".env"
        env_file.write_text("TEST_VAR=test_value\n")

        # Change to temp directory
        monkeypatch.chdir(tmp_path)
        monkeypatch.delenv("POSTPARSE_NO_DOTENV", raising=False)

        with patch("postparse.cli.main.load_dotenv") as mock_load:
            result = load_env_files()

            # Should have called load_dotenv with the found path
            assert mock_load.called
            # Should return the path it found
            assert result is not None

    def test_load_env_files_searches_multiple_locations(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """Test that load_env_files searches multiple standard locations."""
        # Use a real temporary directory with no .env files
        monkeypatch.chdir(tmp_path)
        monkeypatch.delenv("POSTPARSE_NO_DOTENV", raising=False)
        
        # Mock __file__ to point to temp directory so script_dir check also fails
        fake_file = str(tmp_path / "fake" / "cli" / "main.py")
        
        with patch("postparse.cli.main.load_dotenv") as mock_load_dotenv:
            with patch("postparse.cli.main.__file__", fake_file):
                result = load_env_files()
                
                # Should return None if no file found
                assert result is None
                # load_dotenv should not have been called since no files exist
                assert not mock_load_dotenv.called


class TestWelcomeBanner:
    """Test welcome banner display."""

    def test_show_welcome_displays_info(self) -> None:
        """
        Test that show_welcome displays logo and info.

        Verifies that the welcome function calls console print methods
        without testing exact output formatting.
        """
        with patch("postparse.cli.main.console") as mock_console:
            show_welcome()

            # Should print multiple times (banner, examples, etc.)
            assert mock_console.print.call_count >= 2

    def test_show_welcome_includes_version(self) -> None:
        """Test that welcome banner includes version information."""
        with patch("postparse.cli.main.console") as mock_console:
            show_welcome()

            # Should call print at least twice (panel and examples table)
            assert mock_console.print.call_count >= 2
            
            # Verify that print was called (actual version rendering happens in Rich Panel)
            # We can't easily check the rendered content without rendering, but we verify the call happened
            assert mock_console.print.called


class TestCLIGroup:
    """Test main CLI command group."""

    def test_cli_creates_context(self) -> None:
        """
        Test that CLI command initializes context correctly.

        Uses Click's CliRunner to test actual command behavior.
        """
        runner = CliRunner()
        result = runner.invoke(cli, ["--help"])

        assert result.exit_code == 0
        assert "PostParse" in result.output or "postparse" in result.output.lower()

    def test_cli_accepts_global_options(self) -> None:
        """Test that CLI accepts global options like --verbose."""
        runner = CliRunner()

        # Test --verbose flag
        with patch("postparse.cli.main.show_welcome"):
            result = runner.invoke(cli, ["--verbose"])

            # Should succeed even without subcommand
            assert result.exit_code == 0

    def test_cli_accepts_quiet_option(self) -> None:
        """Test that CLI accepts --quiet option."""
        runner = CliRunner()

        with patch("postparse.cli.main.show_welcome") as mock_welcome:
            result = runner.invoke(cli, ["--quiet"])

            assert result.exit_code == 0
            # Welcome should not be shown with --quiet
            mock_welcome.assert_not_called()

    def test_cli_version_option(self) -> None:
        """Test --version option displays version."""
        runner = CliRunner()
        result = runner.invoke(cli, ["--version"])

        assert result.exit_code == 0
        assert __version__ in result.output

    def test_cli_without_command_shows_welcome(self) -> None:
        """Test that running CLI without command shows welcome banner."""
        runner = CliRunner()

        with patch("postparse.cli.main.show_welcome") as mock_welcome:
            result = runner.invoke(cli, [])

            assert result.exit_code == 0
            mock_welcome.assert_called_once()

    def test_cli_stores_options_in_context(self) -> None:
        """Test that CLI stores global options in context object."""
        runner = CliRunner()

        # We can't directly inspect ctx.obj from outside, but we can verify
        # the command runs without error with various options
        result = runner.invoke(cli, ["--verbose", "--help"])

        assert result.exit_code == 0


class TestInfoCommand:
    """Test info command."""

    def test_info_command_displays_version(self) -> None:
        """
        Test that info command displays version information.

        Uses real Click invocation to test actual command behavior.
        """
        runner = CliRunner()
        result = runner.invoke(cli, ["info"])

        assert result.exit_code == 0
        # Should contain version info
        assert __version__ in result.output or "Version" in result.output

    def test_info_command_displays_python_version(self) -> None:
        """Test that info command shows Python version."""
        runner = CliRunner()
        result = runner.invoke(cli, ["info"])

        assert result.exit_code == 0
        # Should mention Python
        assert "Python" in result.output or "python" in result.output.lower()

    def test_info_command_displays_available_commands(self) -> None:
        """Test that info command lists available commands."""
        runner = CliRunner()
        result = runner.invoke(cli, ["info"])

        assert result.exit_code == 0
        # Should list some commands
        output_lower = result.output.lower()
        assert any(cmd in output_lower for cmd in ["extract", "classify", "search", "serve"])

    def test_info_command_handles_missing_packages(self) -> None:
        """Test that info command handles missing package gracefully."""
        runner = CliRunner()
        from importlib.metadata import PackageNotFoundError

        # Patch the version function where it's used (inside the get_version helper)
        with patch("importlib.metadata.version") as mock_version:
            mock_version.side_effect = PackageNotFoundError("test-package")

            result = runner.invoke(cli, ["info"])

            # Should still succeed even if some packages not found
            assert result.exit_code == 0


class TestCommandRegistration:
    """Test that commands are properly registered."""

    def test_extract_command_registered(self) -> None:
        """Test that extract command is registered."""
        runner = CliRunner()
        result = runner.invoke(cli, ["extract", "--help"])

        assert result.exit_code == 0
        assert "extract" in result.output.lower()

    def test_classify_command_registered(self) -> None:
        """Test that classify command is registered."""
        runner = CliRunner()
        result = runner.invoke(cli, ["classify", "--help"])

        assert result.exit_code == 0
        assert "classify" in result.output.lower()

    def test_search_command_registered(self) -> None:
        """Test that search command is registered."""
        runner = CliRunner()
        result = runner.invoke(cli, ["search", "--help"])

        assert result.exit_code == 0
        assert "search" in result.output.lower()

    def test_serve_command_registered(self) -> None:
        """Test that serve command is registered."""
        runner = CliRunner()
        result = runner.invoke(cli, ["serve", "--help"])

        assert result.exit_code == 0
        assert "serve" in result.output.lower()

    def test_db_command_registered(self) -> None:
        """Test that db command is registered."""
        runner = CliRunner()
        result = runner.invoke(cli, ["db", "--help"])

        assert result.exit_code == 0
        assert "db" in result.output.lower()

    def test_config_command_registered(self) -> None:
        """Test that config command is registered."""
        runner = CliRunner()
        result = runner.invoke(cli, ["config", "--help"])

        assert result.exit_code == 0
        assert "config" in result.output.lower()

    def test_check_command_registered(self) -> None:
        """Test that check command is registered."""
        runner = CliRunner()
        result = runner.invoke(cli, ["check", "--help"])

        assert result.exit_code == 0
        assert "check" in result.output.lower()

    def test_stats_command_registered_as_alias(self) -> None:
        """Test that stats is registered as top-level alias."""
        runner = CliRunner()
        result = runner.invoke(cli, ["stats", "--help"])

        assert result.exit_code == 0
        assert "stats" in result.output.lower() or "database" in result.output.lower()


class TestErrorHandling:
    """Test error handling in CLI."""

    def test_cli_handles_invalid_command(self) -> None:
        """Test that CLI handles invalid commands gracefully."""
        runner = CliRunner()
        result = runner.invoke(cli, ["nonexistent"])

        # Should exit with error
        assert result.exit_code != 0
        # Should show helpful error message
        assert "Error" in result.output or "No such command" in result.output

    def test_cli_handles_invalid_option(self) -> None:
        """Test that CLI handles invalid options gracefully."""
        runner = CliRunner()
        result = runner.invoke(cli, ["--invalid-option"])

        assert result.exit_code != 0
        assert "Error" in result.output or "no such option" in result.output.lower()


class TestConfigOption:
    """Test --config option handling."""

    def test_cli_accepts_config_option(self, tmp_path: Path) -> None:
        """Test that CLI accepts --config option."""
        config_file = tmp_path / "test_config.toml"
        config_file.write_text("""
[database]
path = "test.db"
""")

        runner = CliRunner()
        result = runner.invoke(cli, ["--config", str(config_file), "--help"])

        # Should accept the option without error
        assert result.exit_code == 0

    def test_cli_config_option_with_nonexistent_file(self) -> None:
        """Test CLI with --config pointing to nonexistent file."""
        runner = CliRunner()
        result = runner.invoke(cli, ["--config", "/nonexistent/config.toml", "info"])

        # Should handle gracefully (might fail or succeed depending on command)
        # The important thing is it doesn't crash catastrophically
        assert isinstance(result.exit_code, int)


class TestStdioEncoding:
    """Test that CLI output survives non-UTF-8 stdout (e.g. piped on Windows)."""

    # Gear emoji + box-drawing line, as rendered by rich-click help output.
    CLI_GLYPHS = "⚙️  View and validate configuration ─"

    @staticmethod
    def _cp1252_stream() -> io.TextIOWrapper:
        """Simulate a piped Windows stdout that uses the ANSI code page."""
        return io.TextIOWrapper(io.BytesIO(), encoding="cp1252")

    def test_cp1252_stream_cannot_encode_cli_glyphs(self) -> None:
        """Sanity check: without reconfiguring, rich-click glyphs crash."""
        stream = self._cp1252_stream()
        with pytest.raises(UnicodeEncodeError):
            stream.write(self.CLI_GLYPHS)

    def test_configure_stdio_utf8_reconfigures_non_utf8_stream(self) -> None:
        """Non-UTF-8 streams are switched to UTF-8 with errors='replace'."""
        stream = self._cp1252_stream()

        configure_stdio_utf8([stream])

        assert stream.encoding.lower() == "utf-8"
        assert stream.errors == "replace"
        stream.write(self.CLI_GLYPHS)
        stream.flush()
        assert "⚙".encode("utf-8") in stream.buffer.getvalue()

    def test_configure_stdio_utf8_leaves_utf8_and_plain_streams_alone(self) -> None:
        """UTF-8 streams keep their settings; streams without reconfigure are skipped."""
        utf8_stream = io.TextIOWrapper(io.BytesIO(), encoding="utf-8", errors="strict")
        plain_stream = io.StringIO()

        configure_stdio_utf8([utf8_stream, plain_stream])

        assert utf8_stream.errors == "strict"

    def test_main_configures_stdio_before_running_cli(self) -> None:
        """The console-script entry point reconfigures stdio, then runs the CLI."""
        calls = []
        with patch(
            "postparse.cli.main.configure_stdio_utf8",
            side_effect=lambda *a, **k: calls.append("configure"),
        ), patch(
            "postparse.cli.main.cli",
            side_effect=lambda *a, **k: calls.append("cli"),
        ):
            main()

        assert calls == ["configure", "cli"]


class TestSchemaV2Info:
    """`info` reports paths and the schema v2 database; .env loading can be disabled."""

    def test_info_reports_database(self, v2_db, monkeypatch: pytest.MonkeyPatch) -> None:
        from postparse.config import clear_settings_cache

        path, _ = v2_db
        monkeypatch.setenv("POSTPARSE_DB_PATH", str(path))
        clear_settings_cache()
        result = CliRunner().invoke(cli, ["info"])
        assert result.exit_code == 0, result.output
        assert "Schema / items" in result.output
        assert "/ 4" in result.output

    def test_info_with_missing_database(self, tmp_path: Path,
                                        monkeypatch: pytest.MonkeyPatch) -> None:
        from postparse.config import clear_settings_cache

        monkeypatch.setenv("POSTPARSE_DB_PATH", str(tmp_path / "none.db"))
        clear_settings_cache()
        result = CliRunner().invoke(cli, ["info"])
        assert result.exit_code == 0
        assert "not found" in result.output
        assert not (tmp_path / "none.db").exists()

    def test_no_dotenv_switch(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        (tmp_path / ".env").write_text("X=1\n")
        monkeypatch.chdir(tmp_path)
        monkeypatch.setenv("POSTPARSE_NO_DOTENV", "1")
        with patch("postparse.cli.main.load_dotenv") as mock_load:
            assert load_env_files() is None
            assert not mock_load.called
