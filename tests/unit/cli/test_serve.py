"""
Unit tests for CLI serve command.

This module tests the FastAPI server startup command with various
configuration options.
"""

from unittest.mock import MagicMock, patch

import pytest
from click.testing import CliRunner

from postparse.cli.main import cli


class TestServeCommand:
    """Test serve command."""

    def test_serve_with_default_settings(self) -> None:
        """
        Test serve command with default settings.

        Mocks uvicorn at the boundary to test that the command passes
        correct configuration before simulating user interrupt.
        """
        runner = CliRunner()

        with patch("postparse.cli.serve.load_config") as mock_load:
            with patch("uvicorn.run") as mock_uvicorn_run:
                mock_config = MagicMock()
                mock_config.get.side_effect = lambda key, default=None: {
                    "api.host": "0.0.0.0",
                    "api.port": 8000,
                    "api.reload": False,
                    "api.workers": 1,
                    "api.log_level": "info",
                    "api.auth_enabled": False,
                    "api.rate_limiting": False,
                }.get(key, default)
                mock_load.return_value = mock_config

                # Mock uvicorn.run to verify config then simulate user stop
                def verify_config_and_interrupt(app, **kwargs):
                    """Verify uvicorn receives correct config before simulating Ctrl+C."""
                    assert app == "postparse.api.main:app"
                    assert kwargs["host"] == "0.0.0.0"
                    assert kwargs["port"] == 8000
                    assert kwargs["reload"] is False
                    assert kwargs["workers"] == 1
                    assert kwargs["log_level"] == "info"
                    raise KeyboardInterrupt()
                
                mock_uvicorn_run.side_effect = verify_config_and_interrupt

                result = runner.invoke(cli, ["serve"])

                # Should handle interrupt gracefully
                assert result.exit_code == 0
                mock_uvicorn_run.assert_called_once()

    def test_serve_with_custom_host(self) -> None:
        """Test serve command with custom host."""
        runner = CliRunner()

        with patch("postparse.cli.serve.load_config") as mock_load:
            with patch("uvicorn.run") as mock_uvicorn_run:
                mock_config = MagicMock()
                mock_config.get.side_effect = lambda key, default=None: {
                    "api.port": 8000,
                    "api.reload": False,
                    "api.workers": 1,
                    "api.log_level": "info",
                    "api.auth_enabled": False,
                    "api.rate_limiting": False,
                }.get(key, default)
                mock_load.return_value = mock_config

                # Verify custom host is passed correctly
                def verify_custom_host(app, **kwargs):
                    assert kwargs["host"] == "127.0.0.1"
                    raise KeyboardInterrupt()
                
                mock_uvicorn_run.side_effect = verify_custom_host

                result = runner.invoke(cli, ["serve", "--host", "127.0.0.1"])

                assert result.exit_code == 0
                mock_uvicorn_run.assert_called_once()

    def test_serve_with_custom_port(self) -> None:
        """Test serve command with custom port."""
        runner = CliRunner()

        with patch("postparse.cli.serve.load_config") as mock_load:
            with patch("uvicorn.run") as mock_uvicorn_run:
                mock_config = MagicMock()
                mock_config.get.side_effect = lambda key, default=None: {
                    "api.host": "0.0.0.0",
                    "api.reload": False,
                    "api.workers": 1,
                    "api.log_level": "info",
                    "api.auth_enabled": False,
                    "api.rate_limiting": False,
                }.get(key, default)
                mock_load.return_value = mock_config

                # Verify custom port is passed correctly
                def verify_custom_port(app, **kwargs):
                    assert kwargs["port"] == 8080
                    raise KeyboardInterrupt()
                
                mock_uvicorn_run.side_effect = verify_custom_port

                result = runner.invoke(cli, ["serve", "--port", "8080"])

                assert result.exit_code == 0
                mock_uvicorn_run.assert_called_once()

    def test_serve_with_reload_flag(self) -> None:
        """Test serve command with --reload flag for development."""
        runner = CliRunner()

        with patch("postparse.cli.serve.load_config") as mock_load:
            with patch("uvicorn.run") as mock_uvicorn_run:
                mock_config = MagicMock()
                mock_config.get.side_effect = lambda key, default=None: {
                    "api.host": "0.0.0.0",
                    "api.port": 8000,
                    "api.workers": 1,
                    "api.log_level": "info",
                    "api.auth_enabled": False,
                    "api.rate_limiting": False,
                }.get(key, default)
                mock_load.return_value = mock_config

                # Verify reload flag and worker count
                def verify_reload_config(app, **kwargs):
                    assert kwargs["reload"] is True
                    # Workers should be 1 when reload is enabled
                    assert kwargs["workers"] == 1
                    raise KeyboardInterrupt()
                
                mock_uvicorn_run.side_effect = verify_reload_config

                result = runner.invoke(cli, ["serve", "--reload"])

                assert result.exit_code == 0
                mock_uvicorn_run.assert_called_once()

    def test_serve_with_multiple_workers(self) -> None:
        """Test serve command with multiple workers."""
        runner = CliRunner()

        with patch("postparse.cli.serve.load_config") as mock_load:
            with patch("uvicorn.run") as mock_uvicorn_run:
                mock_config = MagicMock()
                mock_config.get.side_effect = lambda key, default=None: {
                    "api.host": "0.0.0.0",
                    "api.port": 8000,
                    "api.reload": False,
                    "api.log_level": "info",
                    "api.auth_enabled": False,
                    "api.rate_limiting": False,
                }.get(key, default)
                mock_load.return_value = mock_config

                # Verify multiple workers configuration
                def verify_workers(app, **kwargs):
                    assert kwargs["workers"] == 4
                    raise KeyboardInterrupt()
                
                mock_uvicorn_run.side_effect = verify_workers

                result = runner.invoke(cli, ["serve", "--workers", "4"])

                assert result.exit_code == 0
                mock_uvicorn_run.assert_called_once()

    def test_serve_with_custom_log_level(self) -> None:
        """Test serve command with custom log level."""
        runner = CliRunner()

        with patch("postparse.cli.serve.load_config") as mock_load:
            with patch("uvicorn.run") as mock_uvicorn_run:
                mock_config = MagicMock()
                mock_config.get.side_effect = lambda key, default=None: {
                    "api.host": "0.0.0.0",
                    "api.port": 8000,
                    "api.reload": False,
                    "api.workers": 1,
                    "api.auth_enabled": False,
                    "api.rate_limiting": False,
                }.get(key, default)
                mock_load.return_value = mock_config

                # Verify custom log level
                def verify_log_level(app, **kwargs):
                    assert kwargs["log_level"] == "debug"
                    raise KeyboardInterrupt()
                
                mock_uvicorn_run.side_effect = verify_log_level

                result = runner.invoke(cli, ["serve", "--log-level", "debug"])

                assert result.exit_code == 0
                mock_uvicorn_run.assert_called_once()

    def test_serve_displays_startup_info(self) -> None:
        """Test that serve displays startup information."""
        runner = CliRunner()

        with patch("postparse.cli.serve.load_config") as mock_load:
            with patch("uvicorn.run") as mock_uvicorn_run:
                mock_config = MagicMock()
                mock_config.get.side_effect = lambda key, default=None: {
                    "api.host": "0.0.0.0",
                    "api.port": 8000,
                    "api.reload": False,
                    "api.workers": 1,
                    "api.log_level": "info",
                    "api.auth_enabled": False,
                    "api.rate_limiting": False,
                }.get(key, default)
                mock_load.return_value = mock_config

                mock_uvicorn_run.side_effect = KeyboardInterrupt()

                result = runner.invoke(cli, ["serve"])

                assert result.exit_code == 0
                # Should display startup info
                output_lower = result.output.lower()
                assert "8000" in result.output or "server" in output_lower

    def test_serve_handles_startup_error(self) -> None:
        """Test that serve handles startup errors gracefully."""
        runner = CliRunner()

        with patch("postparse.cli.serve.load_config") as mock_load:
            with patch("uvicorn.run") as mock_uvicorn_run:
                mock_config = MagicMock()
                mock_config.get.side_effect = lambda key, default=None: {
                    "api.host": "0.0.0.0",
                    "api.port": 8000,
                    "api.reload": False,
                    "api.workers": 1,
                    "api.log_level": "info",
                }.get(key, default)
                mock_load.return_value = mock_config

                # Simulate server startup error
                mock_uvicorn_run.side_effect = Exception("Port already in use")

                result = runner.invoke(cli, ["serve"])

                assert result.exit_code != 0
                # Should show error message
                assert "error" in result.output.lower() or "failed" in result.output.lower()

    def test_serve_uses_config_settings_when_no_options(self) -> None:
        """Test that serve uses config file settings when no CLI options provided."""
        runner = CliRunner()

        with patch("postparse.cli.serve.load_config") as mock_load:
            with patch("uvicorn.run") as mock_uvicorn_run:
                mock_config = MagicMock()
                mock_config.get.side_effect = lambda key, default=None: {
                    "api.host": "localhost",
                    "api.port": 9000,
                    "api.reload": True,
                    "api.workers": 2,
                    "api.log_level": "warning",
                    "api.auth_enabled": True,
                    "api.rate_limiting": True,
                }.get(key, default)
                mock_load.return_value = mock_config

                # Verify config settings are applied correctly
                def verify_config_settings(app, **kwargs):
                    assert kwargs["host"] == "localhost"
                    assert kwargs["port"] == 9000
                    assert kwargs["reload"] is True
                    # Workers should be 1 when reload is True
                    assert kwargs["workers"] == 1
                    assert kwargs["log_level"] == "warning"
                    raise KeyboardInterrupt()
                
                mock_uvicorn_run.side_effect = verify_config_settings

                result = runner.invoke(cli, ["serve"])

                assert result.exit_code == 0
                mock_uvicorn_run.assert_called_once()

    def test_serve_cli_options_override_config(self) -> None:
        """Test that CLI options override config file settings."""
        runner = CliRunner()

        with patch("postparse.cli.serve.load_config") as mock_load:
            with patch("uvicorn.run") as mock_uvicorn_run:
                mock_config = MagicMock()
                mock_config.get.side_effect = lambda key, default=None: {
                    "api.host": "0.0.0.0",
                    "api.port": 8000,
                    "api.reload": False,
                    "api.workers": 1,
                    "api.log_level": "info",
                    "api.auth_enabled": False,
                    "api.rate_limiting": False,
                }.get(key, default)
                mock_load.return_value = mock_config

                # Verify CLI options override config
                def verify_cli_override(app, **kwargs):
                    assert kwargs["port"] == 9999
                    assert kwargs["workers"] == 8
                    raise KeyboardInterrupt()
                
                mock_uvicorn_run.side_effect = verify_cli_override

                result = runner.invoke(
                    cli, ["serve", "--port", "9999", "--workers", "8"]
                )

                assert result.exit_code == 0
                mock_uvicorn_run.assert_called_once()

    def test_serve_passes_correct_app_path(self) -> None:
        """Test that serve passes correct FastAPI app path to uvicorn."""
        runner = CliRunner()

        with patch("postparse.cli.serve.load_config") as mock_load:
            with patch("uvicorn.run") as mock_uvicorn_run:
                mock_config = MagicMock()
                mock_config.get.side_effect = lambda key, default=None: {
                    "api.host": "0.0.0.0",
                    "api.port": 8000,
                    "api.reload": False,
                    "api.workers": 1,
                    "api.log_level": "info",
                    "api.auth_enabled": False,
                    "api.rate_limiting": False,
                }.get(key, default)
                mock_load.return_value = mock_config

                # Verify correct app path is passed
                def verify_app_path(app, **kwargs):
                    assert app == "postparse.api.main:app"
                    raise KeyboardInterrupt()
                
                mock_uvicorn_run.side_effect = verify_app_path

                result = runner.invoke(cli, ["serve"])

                assert result.exit_code == 0
                mock_uvicorn_run.assert_called_once()


class TestServeHelp:
    """Test serve command help output."""

    def test_serve_help_displays_options(self) -> None:
        """Test that serve --help shows available options."""
        runner = CliRunner()
        result = runner.invoke(cli, ["serve", "--help"])

        assert result.exit_code == 0
        output_lower = result.output.lower()
        assert "serve" in output_lower
        assert "host" in output_lower
        assert "port" in output_lower
        assert "reload" in output_lower
        assert "workers" in output_lower
        assert "log-level" in output_lower

    def test_serve_help_mentions_docs(self) -> None:
        """Test that serve help mentions API documentation URLs."""
        runner = CliRunner()
        result = runner.invoke(cli, ["serve", "--help"])

        assert result.exit_code == 0
        # Should mention docs or API
        output_lower = result.output.lower()
        assert "api" in output_lower or "docs" in output_lower or "swagger" in output_lower


class TestServeConfiguration:
    """Test serve command configuration handling."""

    def test_serve_with_invalid_log_level(self) -> None:
        """Test that serve rejects invalid log level."""
        runner = CliRunner()

        result = runner.invoke(cli, ["serve", "--log-level", "invalid"])

        # Should fail with invalid choice
        assert result.exit_code != 0
        assert "invalid" in result.output.lower() or "choice" in result.output.lower()

    def test_serve_displays_auth_status(self) -> None:
        """Test that serve displays authentication status."""
        runner = CliRunner()

        with patch("postparse.cli.serve.load_config") as mock_load:
            with patch("uvicorn.run") as mock_uvicorn_run:
                mock_config = MagicMock()
                mock_config.get.side_effect = lambda key, default=None: {
                    "api.host": "0.0.0.0",
                    "api.port": 8000,
                    "api.reload": False,
                    "api.workers": 1,
                    "api.log_level": "info",
                    "api.auth_enabled": True,
                    "api.rate_limiting": False,
                }.get(key, default)
                mock_load.return_value = mock_config

                # Verify config is used, then interrupt
                def verify_and_interrupt(app, **kwargs):
                    raise KeyboardInterrupt()
                
                mock_uvicorn_run.side_effect = verify_and_interrupt

                result = runner.invoke(cli, ["serve"])

                assert result.exit_code == 0
                # Should show auth status in startup output
                output_lower = result.output.lower()
                assert "auth" in output_lower or "true" in output_lower

    def test_serve_displays_rate_limiting_status(self) -> None:
        """Test that serve displays rate limiting status."""
        runner = CliRunner()

        with patch("postparse.cli.serve.load_config") as mock_load:
            with patch("uvicorn.run") as mock_uvicorn_run:
                mock_config = MagicMock()
                mock_config.get.side_effect = lambda key, default=None: {
                    "api.host": "0.0.0.0",
                    "api.port": 8000,
                    "api.reload": False,
                    "api.workers": 1,
                    "api.log_level": "info",
                    "api.auth_enabled": False,
                    "api.rate_limiting": True,
                }.get(key, default)
                mock_load.return_value = mock_config

                # Verify config is used, then interrupt
                def verify_and_interrupt(app, **kwargs):
                    raise KeyboardInterrupt()
                
                mock_uvicorn_run.side_effect = verify_and_interrupt

                result = runner.invoke(cli, ["serve"])

                assert result.exit_code == 0
                # Should show rate limiting status in startup output
                output_lower = result.output.lower()
                assert "rate" in output_lower or "limiting" in output_lower or "true" in output_lower

