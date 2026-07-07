"""
Unit tests for CLI config commands.

This module tests configuration management commands including showing,
validating, and displaying environment variables.
"""

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from click.testing import CliRunner

from backend.postparse.cli.main import cli


class TestConfigShow:
    """Test config show command."""

    def test_config_show_displays_configuration(self, tmp_path: Path) -> None:
        """
        Test that config show displays configuration.

        Creates a temporary config and verifies the command displays it.
        """
        config_file = tmp_path / "config.toml"
        config_file.write_text("""
[database]
path = "data/test.db"

[api]
port = 8000
host = "0.0.0.0"

[llm]
[[llm.providers]]
name = "test_provider"
base_url = "http://localhost:8000"
model_name = "test-model"
""")

        runner = CliRunner()

        with patch("backend.postparse.cli.config.load_config") as mock_load:
            mock_config = MagicMock()
            mock_config.config_path = config_file
            mock_config.get_section.side_effect = lambda section: {
                "llm": {"providers": [{"name": "test_provider", "base_url": "http://localhost:8000", "model_name": "test-model", "api_key": None}]},
                "api": {"host": "0.0.0.0", "port": 8000, "reload": False, "workers": 1, "log_level": "info", "auth_enabled": False, "rate_limiting": False},
                "database": {"path": "data/test.db"},
            }.get(section, {})
            mock_config.get.side_effect = lambda key, default=None: {
                "database.path": "data/test.db",
            }.get(key, default)
            mock_load.return_value = mock_config

            result = runner.invoke(cli, ["config", "show"])

            assert result.exit_code == 0
            # Should display some config info
            assert "data/test.db" in result.output or "database" in result.output.lower()

    def test_config_show_specific_section(self) -> None:
        """Test showing specific configuration section."""
        runner = CliRunner()

        with patch("backend.postparse.cli.config.load_config") as mock_load:
            mock_config = MagicMock()
            mock_config.config_path = Path("config.toml")
            mock_config.get_section.return_value = {"port": 8000, "host": "0.0.0.0"}
            mock_config.get.return_value = None
            mock_load.return_value = mock_config

            result = runner.invoke(cli, ["config", "show", "--section", "api"])

            assert result.exit_code == 0

    def test_config_show_json_format(self) -> None:
        """Test config show with JSON output format."""
        runner = CliRunner()

        with patch("backend.postparse.cli.config.load_config") as mock_load:
            mock_config = MagicMock()
            mock_config.config_path = Path("config.toml")
            mock_config.get_section.return_value = {"providers": []}
            mock_config.get.return_value = "data/test.db"
            mock_load.return_value = mock_config

            result = runner.invoke(cli, ["config", "show", "--format", "json"])

            assert result.exit_code == 0
            # JSON output should be present
            assert "{" in result.output or "database" in result.output

    def test_config_show_handles_error(self) -> None:
        """Test that config show handles errors gracefully."""
        runner = CliRunner()

        with patch("backend.postparse.cli.config.load_config") as mock_load:
            mock_load.side_effect = Exception("Config load failed")

            result = runner.invoke(cli, ["config", "show"])

            # Should handle error gracefully
            assert result.exit_code != 0
            assert "error" in result.output.lower() or "failed" in result.output.lower()


class TestConfigValidate:
    """Test config validate command."""

    def test_config_validate_passes_with_valid_config(self) -> None:
        """
        Test that validate passes with valid configuration.

        Uses real validation logic with mocked config at the boundary.
        """
        runner = CliRunner()

        with patch("backend.postparse.cli.config.load_config") as mock_load:
            mock_config = MagicMock()
            mock_config.config_path = Path("config.toml")
            mock_config.get.side_effect = lambda key, default=None: {
                "database.path": "data/test.db",
                "database.default_db_path": "data/test.db",
                "api.port": 8000,
            }.get(key, default)
            mock_config.get_section.return_value = {
                "providers": [
                    {"name": "test", "base_url": "http://localhost:8000"}
                ]
            }
            mock_load.return_value = mock_config

            with patch("pathlib.Path.exists", return_value=True):
                result = runner.invoke(cli, ["config", "validate"])

                assert result.exit_code == 0
                # Should show success message
                assert "pass" in result.output.lower() or "success" in result.output.lower()

    def test_config_validate_detects_missing_database_dir(self, tmp_path: Path) -> None:
        """Test that validate detects missing database directory."""
        runner = CliRunner()

        with patch("backend.postparse.cli.config.load_config") as mock_load:
            mock_config = MagicMock()
            mock_config.config_path = Path("config.toml")
            nonexistent_path = tmp_path / "nonexistent" / "test.db"
            mock_config.get.side_effect = lambda key, default=None: {
                "database.path": str(nonexistent_path),
                "database.default_db_path": str(nonexistent_path),
                "api.port": 8000,
            }.get(key, default)
            mock_config.get_section.return_value = {"providers": []}
            mock_load.return_value = mock_config

            result = runner.invoke(cli, ["config", "validate"])

            # Should fail or show warning about missing directory
            assert "database" in result.output.lower() or "directory" in result.output.lower()

    def test_config_validate_fix_creates_directories(self, tmp_path: Path) -> None:
        """Test that validate --fix creates missing directories."""
        runner = CliRunner()

        db_path = tmp_path / "data" / "test.db"

        with patch("backend.postparse.cli.config.load_config") as mock_load:
            mock_config = MagicMock()
            mock_config.config_path = Path("config.toml")
            mock_config.get.side_effect = lambda key, default=None: {
                "database.path": str(db_path),
                "database.default_db_path": str(db_path),
                "api.port": 8000,
            }.get(key, default)
            mock_config.get_section.return_value = {"providers": []}
            mock_load.return_value = mock_config

            result = runner.invoke(cli, ["config", "validate", "--fix"])

            # Should create the directory
            assert db_path.parent.exists()

    def test_config_validate_detects_invalid_port(self) -> None:
        """Test that validate detects invalid API port."""
        runner = CliRunner()

        with patch("backend.postparse.cli.config.load_config") as mock_load:
            mock_config = MagicMock()
            mock_config.config_path = Path("config.toml")
            mock_config.get.side_effect = lambda key, default=None: {
                "database.path": "data/test.db",
                "api.port": 99999,  # Invalid port
            }.get(key, default)
            mock_config.get_section.return_value = {"providers": []}
            mock_load.return_value = mock_config

            with patch("pathlib.Path.exists", return_value=True):
                result = runner.invoke(cli, ["config", "validate"])

                # Should detect invalid port
                assert "port" in result.output.lower() or "fail" in result.output.lower()

    def test_config_validate_warns_about_missing_llm_providers(self) -> None:
        """Test that validate warns about missing LLM providers."""
        runner = CliRunner()

        with patch("backend.postparse.cli.config.load_config") as mock_load:
            mock_config = MagicMock()
            mock_config.config_path = Path("config.toml")
            mock_config.get.side_effect = lambda key, default=None: {
                "database.path": "data/test.db",
                "api.port": 8000,
            }.get(key, default)
            mock_config.get_section.return_value = {"providers": []}  # No providers
            mock_load.return_value = mock_config

            with patch("pathlib.Path.exists", return_value=True):
                result = runner.invoke(cli, ["config", "validate"])

                # Should warn about missing providers
                assert "llm" in result.output.lower() or "provider" in result.output.lower()

    def test_config_validate_handles_config_load_error(self) -> None:
        """Test that validate handles config loading errors."""
        runner = CliRunner()

        with patch("backend.postparse.cli.config.load_config") as mock_load:
            mock_load.side_effect = Exception("Config not found")

            result = runner.invoke(cli, ["config", "validate"])

            # Should handle error gracefully (click.Abort() gives exit code 1)
            assert result.exit_code == 1


class TestConfigEnv:
    """Test config env command."""

    def test_config_env_displays_env_vars(self) -> None:
        """
        Test that config env displays environment variables.

        Tests the real command behavior with mocked environment.
        """
        runner = CliRunner()

        with patch("os.getenv") as mock_getenv:
            # Mock some environment variables
            mock_getenv.side_effect = lambda key: {
                "_POSTPARSE_ENV_FILE": "/path/to/.env",
                "TELEGRAM_API_ID": "12345",
                "TELEGRAM_API_HASH": "abc123",
            }.get(key)

            result = runner.invoke(cli, ["config", "env"])

            assert result.exit_code == 0
            # Should show telegram credentials status
            assert "telegram" in result.output.lower() or "api" in result.output.lower()

    def test_config_env_masks_sensitive_values(self) -> None:
        """Test that config env masks sensitive credential values."""
        runner = CliRunner()

        with patch("os.getenv") as mock_getenv:
            mock_getenv.side_effect = lambda key: {
                "OPENAI_API_KEY": "sk-verylongsecretkey123456",
            }.get(key)

            result = runner.invoke(cli, ["config", "env"])

            assert result.exit_code == 0
            # Should mask the key (show *** or partial)
            assert "***" in result.output or "Set" in result.output

    def test_config_env_shows_loaded_file_path(self) -> None:
        """Test that config env shows which .env file was loaded."""
        runner = CliRunner()

        with patch("os.getenv") as mock_getenv:
            mock_getenv.side_effect = lambda key: {
                "_POSTPARSE_ENV_FILE": "/path/to/config/.env",
            }.get(key)

            result = runner.invoke(cli, ["config", "env"])

            assert result.exit_code == 0
            # Should mention the loaded file
            assert ".env" in result.output

    def test_config_env_shows_warning_when_no_file_found(self) -> None:
        """Test that config env warns when no .env file found."""
        runner = CliRunner()

        with patch("os.getenv", return_value=None):
            result = runner.invoke(cli, ["config", "env"])

            assert result.exit_code == 0
            # Should show warning about no file found
            assert "no" in result.output.lower() or "not found" in result.output.lower()

    def test_config_env_displays_current_directory(self) -> None:
        """Test that config env displays current working directory."""
        runner = CliRunner()

        with patch("os.getenv", return_value=None):
            result = runner.invoke(cli, ["config", "env"])

            assert result.exit_code == 0
            # Should show current directory
            assert "directory" in result.output.lower() or "cwd" in result.output.lower()


class TestConfigHelp:
    """Test config command help output."""

    def test_config_help_displays_subcommands(self) -> None:
        """Test that config --help shows available subcommands."""
        runner = CliRunner()
        result = runner.invoke(cli, ["config", "--help"])

        assert result.exit_code == 0
        # Should list subcommands
        output_lower = result.output.lower()
        assert "show" in output_lower
        assert "validate" in output_lower
        assert "env" in output_lower

    def test_config_show_help(self) -> None:
        """Test config show --help displays help text."""
        runner = CliRunner()
        result = runner.invoke(cli, ["config", "show", "--help"])

        assert result.exit_code == 0
        assert "show" in result.output.lower()
        # Should mention format options
        assert "format" in result.output.lower() or "json" in result.output.lower()

    def test_config_validate_help(self) -> None:
        """Test config validate --help displays help text."""
        runner = CliRunner()
        result = runner.invoke(cli, ["config", "validate", "--help"])

        assert result.exit_code == 0
        assert "validate" in result.output.lower()
        # Should mention --fix option
        assert "fix" in result.output.lower()


class TestDisplayValidationResults:
    """Test the display_validation_results helper function."""

    def test_display_validation_results_with_passes(self) -> None:
        """Test displaying validation results with passed checks."""
        from backend.postparse.cli.config import display_validation_results
        from unittest.mock import MagicMock

        results = [
            {"check": "Test 1", "status": "pass", "message": "OK"},
            {"check": "Test 2", "status": "pass", "message": "OK"},
        ]

        mock_console = MagicMock()
        display_validation_results(mock_console, results)

        # Should print table
        mock_console.print.assert_called_once()

    def test_display_validation_results_with_failures(self) -> None:
        """Test displaying validation results with failures."""
        from backend.postparse.cli.config import display_validation_results
        from unittest.mock import MagicMock

        results = [
            {"check": "Test 1", "status": "fail", "message": "Failed"},
            {"check": "Test 2", "status": "warning", "message": "Warning"},
        ]

        mock_console = MagicMock()
        display_validation_results(mock_console, results)

        mock_console.print.assert_called_once()

    def test_display_validation_results_formats_status_correctly(self) -> None:
        """Test that validation results format status correctly."""
        from backend.postparse.cli.config import display_validation_results
        from unittest.mock import MagicMock

        results = [
            {"check": "Pass test", "status": "pass", "message": "OK"},
            {"check": "Fail test", "status": "fail", "message": "Error"},
            {"check": "Warn test", "status": "warning", "message": "Warning"},
        ]

        mock_console = MagicMock()
        display_validation_results(mock_console, results)

        # Should print table with all results
        assert mock_console.print.called

