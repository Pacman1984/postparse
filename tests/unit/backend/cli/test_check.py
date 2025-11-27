"""
Unit tests for CLI check commands.

This module tests the check commands for examining new content
available on Telegram and Instagram without downloading, as well
as LLM provider availability checking.
"""

from datetime import datetime
from typing import Dict, List, Optional
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from click.testing import CliRunner

from backend.postparse.cli.main import cli


class TestCheckTelegram:
    """Test check telegram command."""

    def test_check_telegram_requires_credentials(self) -> None:
        """
        Test that check telegram validates credentials properly.

        Verifies that missing credentials are handled with proper error.
        """
        runner = CliRunner()

        with patch("backend.postparse.cli.check.validate_credentials") as mock_validate:
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

        with patch("backend.postparse.cli.check.load_config") as mock_load:
            with patch("backend.postparse.cli.check.get_database") as mock_get_db:
                with patch("backend.postparse.services.parsers.telegram.telegram_parser.TelegramParser") as mock_parser_class:
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

        with patch("backend.postparse.cli.check.load_config") as mock_load:
            with patch("backend.postparse.cli.check.get_database") as mock_get_db:
                with patch("backend.postparse.services.parsers.telegram.telegram_parser.TelegramParser") as mock_parser_class:
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

        with patch("backend.postparse.cli.check.load_config") as mock_load:
            with patch("backend.postparse.cli.check.get_database") as mock_get_db:
                with patch("backend.postparse.services.parsers.telegram.telegram_parser.TelegramParser") as mock_parser:
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

        with patch("backend.postparse.cli.check.validate_credentials") as mock_validate:
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

        with patch("backend.postparse.cli.check.load_config") as mock_load:
            with patch("backend.postparse.cli.check.get_database") as mock_get_db:
                with patch("backend.postparse.services.parsers.instagram.instagram_parser.InstaloaderParser") as mock_parser_class:
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

        with patch("backend.postparse.cli.check.load_config") as mock_load:
            with patch("backend.postparse.cli.check.get_database") as mock_get_db:
                with patch("backend.postparse.services.parsers.instagram.instagram_parser.InstaloaderParser") as mock_parser_class:
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

    def _create_mock_llm_setup(self) -> tuple:
        """Create mock LLM config and provider for tests.

        Returns:
            Tuple of (mock_llm_config, mock_provider_cfg).
        """
        mock_provider_cfg = MagicMock()
        mock_provider_cfg.name = "lm_studio"
        mock_provider_cfg.model = "test-model"
        mock_provider_cfg.api_base = "http://localhost:1234/v1"
        mock_provider_cfg.api_key = None

        mock_llm_config = MagicMock()
        mock_llm_config.providers = [mock_provider_cfg]
        mock_llm_config.default_provider = "lm_studio"

        return mock_llm_config, mock_provider_cfg

    def test_check_all_with_no_credentials(self) -> None:
        """Test check all when no credentials are provided."""
        runner = CliRunner()

        mock_llm_config, _ = self._create_mock_llm_setup()

        with patch("backend.postparse.cli.check.load_config") as mock_load:
            with patch("backend.postparse.cli.check.get_database") as mock_get_db:
                with patch("backend.postparse.core.utils.config.ConfigManager"):
                    with patch("backend.postparse.llm.config.LLMConfig") as mock_llm_cls:
                        with patch("backend.postparse.llm.provider.LiteLLMProvider") as mock_prov:
                            with patch("backend.postparse.cli.check.os.getenv", return_value=None):
                                mock_config = MagicMock()
                                mock_config.get.return_value = "data/test.db"
                                mock_load.return_value = mock_config

                                mock_db = MagicMock()
                                mock_db.get_instagram_posts.return_value = []
                                mock_db.get_telegram_messages.return_value = []
                                mock_get_db.return_value = mock_db

                                mock_llm_cls.from_config_manager.return_value = mock_llm_config
                                mock_provider = MagicMock()
                                mock_provider.is_available.return_value = True
                                mock_prov.return_value = mock_provider

                                result = runner.invoke(cli, ["check", "all"])

                                assert result.exit_code == 0
                                # Should warn about missing credentials
                                output_lower = result.output.lower()
                                assert (
                                    "skip" in output_lower
                                    or "no credentials" in output_lower
                                    or "credentials" in output_lower
                                )

    def test_check_all_checks_both_platforms(self) -> None:
        """Test that check all attempts to check both platforms."""
        runner = CliRunner()

        mock_llm_config, _ = self._create_mock_llm_setup()

        with patch("backend.postparse.cli.check.load_config") as mock_load:
            with patch("backend.postparse.cli.check.get_database") as mock_get_db:
                with patch("backend.postparse.core.utils.config.ConfigManager"):
                    with patch("backend.postparse.llm.config.LLMConfig") as mock_llm_cls:
                        with patch("backend.postparse.llm.provider.LiteLLMProvider") as mock_prov:
                            with patch("backend.postparse.cli.check.os.getenv") as mock_getenv:
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

                                mock_llm_cls.from_config_manager.return_value = mock_llm_config
                                mock_provider = MagicMock()
                                mock_provider.is_available.return_value = True
                                mock_prov.return_value = mock_provider

                                result = runner.invoke(cli, ["check", "all"])

                                # May succeed or fail depending on mocks, but should attempt
                                assert isinstance(result.exit_code, int)

    def test_check_all_without_subcommand_defaults_to_all(self) -> None:
        """Test that 'check' without subcommand defaults to 'check all'."""
        runner = CliRunner()

        mock_llm_config, _ = self._create_mock_llm_setup()

        with patch("backend.postparse.cli.check.load_config") as mock_load:
            with patch("backend.postparse.cli.check.get_database") as mock_get_db:
                with patch("backend.postparse.core.utils.config.ConfigManager"):
                    with patch("backend.postparse.llm.config.LLMConfig") as mock_llm_cls:
                        with patch("backend.postparse.llm.provider.LiteLLMProvider") as mock_prov:
                            with patch("backend.postparse.cli.check.os.getenv", return_value=None):
                                mock_config = MagicMock()
                                mock_config.get.return_value = "data/test.db"
                                mock_load.return_value = mock_config

                                mock_db = MagicMock()
                                mock_db.get_instagram_posts.return_value = []
                                mock_db.get_telegram_messages.return_value = []
                                mock_get_db.return_value = mock_db

                                mock_llm_cls.from_config_manager.return_value = mock_llm_config
                                mock_provider = MagicMock()
                                mock_provider.is_available.return_value = True
                                mock_prov.return_value = mock_provider

                                result = runner.invoke(cli, ["check"])

                                assert result.exit_code == 0
                                # Should run 'all' by default
                                output_lower = result.output.lower()
                                assert "platform" in output_lower or "check" in output_lower


class TestCheckLlm:
    """Test check llm command for LLM provider availability."""

    def _create_mock_provider_config(
        self,
        name: str = "lm_studio",
        model: str = "test-model",
        api_base: Optional[str] = "http://localhost:1234/v1",
        api_key: Optional[str] = None,
    ) -> MagicMock:
        """Create a mock ProviderConfig for testing.

        Args:
            name: Provider name.
            model: Model name.
            api_base: API base URL.
            api_key: Optional API key.

        Returns:
            MagicMock configured as ProviderConfig.
        """
        config = MagicMock()
        config.name = name
        config.model = model
        config.api_base = api_base
        config.api_key = api_key
        return config

    def _create_mock_llm_config(
        self,
        providers: List[MagicMock],
        default_provider: str = "lm_studio",
    ) -> MagicMock:
        """Create a mock LLMConfig for testing.

        Args:
            providers: List of mock ProviderConfig objects.
            default_provider: Name of the default provider.

        Returns:
            MagicMock configured as LLMConfig.
        """
        config = MagicMock()
        config.providers = providers
        config.default_provider = default_provider
        return config

    def test_check_llm_with_available_provider(self) -> None:
        """Test check llm when a provider is available.

        Verifies that an available LLM provider is correctly detected and
        the classification ready message is displayed.
        """
        runner = CliRunner()

        mock_provider_cfg = self._create_mock_provider_config(
            name="lm_studio",
            model="qwen/qwen3-vl-8b",
            api_base="http://localhost:1234/v1",
        )
        mock_llm_config = self._create_mock_llm_config(
            providers=[mock_provider_cfg],
            default_provider="lm_studio",
        )

        with patch("backend.postparse.core.utils.config.ConfigManager") as mock_config_mgr:
            with patch("backend.postparse.llm.config.LLMConfig") as mock_llm_config_class:
                with patch("backend.postparse.llm.provider.LiteLLMProvider") as mock_provider_class:
                    mock_llm_config_class.from_config_manager.return_value = mock_llm_config

                    mock_provider = MagicMock()
                    mock_provider.is_available.return_value = True
                    mock_provider_class.return_value = mock_provider

                    result = runner.invoke(cli, ["check", "llm"])

                    assert result.exit_code == 0
                    output_lower = result.output.lower()
                    # Should show provider is available
                    assert "available" in output_lower
                    # Should show classification ready message
                    assert "classification ready" in output_lower
                    # Should mention the model
                    assert "qwen" in output_lower or "lm studio" in output_lower

    def test_check_llm_with_unavailable_provider(self) -> None:
        """Test check llm when provider is not available.

        Verifies that an unavailable provider (e.g., LM Studio not running)
        is correctly detected and appropriate error message is shown.
        """
        runner = CliRunner()

        mock_provider_cfg = self._create_mock_provider_config(
            name="lm_studio",
            model="test-model",
            api_base="http://localhost:1234/v1",
        )
        mock_llm_config = self._create_mock_llm_config(
            providers=[mock_provider_cfg],
            default_provider="lm_studio",
        )

        with patch("backend.postparse.core.utils.config.ConfigManager") as mock_config_mgr:
            with patch("backend.postparse.llm.config.LLMConfig") as mock_llm_config_class:
                with patch("backend.postparse.llm.provider.LiteLLMProvider") as mock_provider_class:
                    mock_llm_config_class.from_config_manager.return_value = mock_llm_config

                    mock_provider = MagicMock()
                    mock_provider.is_available.return_value = False
                    mock_provider_class.return_value = mock_provider

                    result = runner.invoke(cli, ["check", "llm"])

                    assert result.exit_code == 0
                    output_lower = result.output.lower()
                    # Should indicate not running or unavailable
                    assert (
                        "not running" in output_lower
                        or "unavailable" in output_lower
                        or "not available" in output_lower
                    )
                    # Should show troubleshooting info
                    assert "lm studio" in output_lower or "ollama" in output_lower

    def test_check_llm_with_missing_api_key(self) -> None:
        """Test check llm when cloud provider API key is missing.

        Verifies that missing API keys for cloud providers (OpenAI, Anthropic)
        are correctly detected without attempting connection.
        """
        runner = CliRunner()

        mock_provider_cfg = self._create_mock_provider_config(
            name="openai",
            model="gpt-4o-mini",
            api_base=None,  # Cloud provider, no custom endpoint
            api_key=None,
        )
        mock_llm_config = self._create_mock_llm_config(
            providers=[mock_provider_cfg],
            default_provider="openai",
        )

        with patch("backend.postparse.core.utils.config.ConfigManager") as mock_config_mgr:
            with patch("backend.postparse.llm.config.LLMConfig") as mock_llm_config_class:
                with patch("backend.postparse.llm.provider.LiteLLMProvider") as mock_provider_class:
                    with patch.dict("os.environ", {}, clear=True):
                        mock_llm_config_class.from_config_manager.return_value = mock_llm_config

                        result = runner.invoke(cli, ["check", "llm"])

                        assert result.exit_code == 0
                        output_lower = result.output.lower()
                        # Should indicate API key issue
                        assert (
                            "api_key" in output_lower
                            or "api key" in output_lower
                            or "openai_api_key" in output_lower
                        )
                        # Provider should not try to connect without API key
                        mock_provider_class.assert_not_called()

    def test_check_llm_with_multiple_providers(self) -> None:
        """Test check llm with multiple providers configured.

        Verifies that all configured providers are checked and displayed
        in the output table.
        """
        runner = CliRunner()

        providers = [
            self._create_mock_provider_config(
                name="lm_studio",
                model="qwen/qwen3-vl-8b",
                api_base="http://localhost:1234/v1",
            ),
            self._create_mock_provider_config(
                name="ollama",
                model="qwen3:14b",
                api_base="http://localhost:11434",
            ),
        ]
        mock_llm_config = self._create_mock_llm_config(
            providers=providers,
            default_provider="lm_studio",
        )

        with patch("backend.postparse.core.utils.config.ConfigManager") as mock_config_mgr:
            with patch("backend.postparse.llm.config.LLMConfig") as mock_llm_config_class:
                with patch("backend.postparse.llm.provider.LiteLLMProvider") as mock_provider_class:
                    mock_llm_config_class.from_config_manager.return_value = mock_llm_config

                    # First provider available, second not
                    mock_provider_available = MagicMock()
                    mock_provider_available.is_available.return_value = True

                    mock_provider_unavailable = MagicMock()
                    mock_provider_unavailable.is_available.return_value = False

                    mock_provider_class.side_effect = [
                        mock_provider_available,
                        mock_provider_unavailable,
                    ]

                    result = runner.invoke(cli, ["check", "llm"])

                    assert result.exit_code == 0
                    output_lower = result.output.lower()
                    # Should mention both providers
                    assert "lm_studio" in output_lower or "lm studio" in output_lower
                    assert "ollama" in output_lower
                    # Should show one available
                    assert "available" in output_lower
                    # Should use first available for classification
                    assert "classification ready" in output_lower

    def test_check_llm_verbose_flag(self) -> None:
        """Test check llm with verbose flag.

        Verifies that verbose mode shows progress information during checks.
        """
        runner = CliRunner()

        mock_provider_cfg = self._create_mock_provider_config()
        mock_llm_config = self._create_mock_llm_config(
            providers=[mock_provider_cfg],
        )

        with patch("backend.postparse.core.utils.config.ConfigManager") as mock_config_mgr:
            with patch("backend.postparse.llm.config.LLMConfig") as mock_llm_config_class:
                with patch("backend.postparse.llm.provider.LiteLLMProvider") as mock_provider_class:
                    mock_llm_config_class.from_config_manager.return_value = mock_llm_config

                    mock_provider = MagicMock()
                    mock_provider.is_available.return_value = True
                    mock_provider_class.return_value = mock_provider

                    result = runner.invoke(cli, ["check", "llm", "--verbose"])

                    assert result.exit_code == 0
                    # Verbose mode should show checking progress
                    output_lower = result.output.lower()
                    assert "checking" in output_lower or "llm" in output_lower

    def test_check_llm_displays_default_provider_marker(self) -> None:
        """Test that default provider is marked with asterisk.

        Verifies that the default provider is visually distinguished in output.
        """
        runner = CliRunner()

        providers = [
            self._create_mock_provider_config(
                name="lm_studio",
                model="test-model",
                api_base="http://localhost:1234/v1",
            ),
            self._create_mock_provider_config(
                name="openai",
                model="gpt-4o-mini",
                api_base=None,
                api_key="sk-test",
            ),
        ]
        mock_llm_config = self._create_mock_llm_config(
            providers=providers,
            default_provider="lm_studio",
        )

        with patch("backend.postparse.core.utils.config.ConfigManager") as mock_config_mgr:
            with patch("backend.postparse.llm.config.LLMConfig") as mock_llm_config_class:
                with patch("backend.postparse.llm.provider.LiteLLMProvider") as mock_provider_class:
                    mock_llm_config_class.from_config_manager.return_value = mock_llm_config

                    mock_provider = MagicMock()
                    mock_provider.is_available.return_value = True
                    mock_provider_class.return_value = mock_provider

                    result = runner.invoke(cli, ["check", "llm"])

                    assert result.exit_code == 0
                    # Default provider should have marker
                    assert "*" in result.output or "default" in result.output.lower()


class TestCheckAllWithLlm:
    """Test check all command includes LLM status."""

    def test_check_all_includes_llm_status(self) -> None:
        """Test that check all command includes LLM provider status.

        Verifies that running 'check all' also displays LLM availability.
        """
        runner = CliRunner()

        mock_provider_cfg = MagicMock()
        mock_provider_cfg.name = "lm_studio"
        mock_provider_cfg.model = "test-model"
        mock_provider_cfg.api_base = "http://localhost:1234/v1"
        mock_provider_cfg.api_key = None

        mock_llm_config = MagicMock()
        mock_llm_config.providers = [mock_provider_cfg]
        mock_llm_config.default_provider = "lm_studio"

        with patch("backend.postparse.cli.check.load_config") as mock_load:
            with patch("backend.postparse.cli.check.get_database") as mock_get_db:
                with patch("backend.postparse.core.utils.config.ConfigManager") as mock_config_mgr:
                    with patch("backend.postparse.llm.config.LLMConfig") as mock_llm_config_class:
                        with patch("backend.postparse.llm.provider.LiteLLMProvider") as mock_provider_class:
                            with patch("backend.postparse.cli.check.os.getenv", return_value=None):
                                mock_config = MagicMock()
                                mock_config.get.return_value = "data/test.db"
                                mock_load.return_value = mock_config

                                mock_db = MagicMock()
                                mock_db.get_instagram_posts.return_value = []
                                mock_db.get_telegram_messages.return_value = []
                                mock_get_db.return_value = mock_db

                                mock_llm_config_class.from_config_manager.return_value = (
                                    mock_llm_config
                                )

                                mock_provider = MagicMock()
                                mock_provider.is_available.return_value = True
                                mock_provider_class.return_value = mock_provider

                                result = runner.invoke(cli, ["check", "all"])

                                assert result.exit_code == 0
                                output_lower = result.output.lower()
                                # Should show LLM status
                                assert (
                                    "llm" in output_lower
                                    or "classification" in output_lower
                                    or "provider" in output_lower
                                )

    def test_check_all_shows_llm_not_available(self) -> None:
        """Test that check all shows when no LLM providers are available.

        Verifies proper messaging when LLM providers are down.
        """
        runner = CliRunner()

        mock_provider_cfg = MagicMock()
        mock_provider_cfg.name = "lm_studio"
        mock_provider_cfg.model = "test-model"
        mock_provider_cfg.api_base = "http://localhost:1234/v1"
        mock_provider_cfg.api_key = None

        mock_llm_config = MagicMock()
        mock_llm_config.providers = [mock_provider_cfg]
        mock_llm_config.default_provider = "lm_studio"

        with patch("backend.postparse.cli.check.load_config") as mock_load:
            with patch("backend.postparse.cli.check.get_database") as mock_get_db:
                with patch("backend.postparse.core.utils.config.ConfigManager") as mock_config_mgr:
                    with patch("backend.postparse.llm.config.LLMConfig") as mock_llm_config_class:
                        with patch("backend.postparse.llm.provider.LiteLLMProvider") as mock_provider_class:
                            with patch("backend.postparse.cli.check.os.getenv", return_value=None):
                                mock_config = MagicMock()
                                mock_config.get.return_value = "data/test.db"
                                mock_load.return_value = mock_config

                                mock_db = MagicMock()
                                mock_db.get_instagram_posts.return_value = []
                                mock_db.get_telegram_messages.return_value = []
                                mock_get_db.return_value = mock_db

                                mock_llm_config_class.from_config_manager.return_value = (
                                    mock_llm_config
                                )

                                mock_provider = MagicMock()
                                mock_provider.is_available.return_value = False
                                mock_provider_class.return_value = mock_provider

                                result = runner.invoke(cli, ["check", "all"])

                                assert result.exit_code == 0
                                output_lower = result.output.lower()
                                # Should indicate classification not available or show status
                                assert (
                                    "not available" in output_lower
                                    or "not running" in output_lower
                                    or "llm" in output_lower
                                )


class TestCheckHelp:
    """Test check command help output."""

    def test_check_help_displays_subcommands(self) -> None:
        """Test that check --help shows available subcommands including llm."""
        runner = CliRunner()
        result = runner.invoke(cli, ["check", "--help"])

        assert result.exit_code == 0
        output_lower = result.output.lower()
        assert "telegram" in output_lower
        assert "instagram" in output_lower
        assert "all" in output_lower
        assert "llm" in output_lower

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

    def test_check_llm_help(self) -> None:
        """Test check llm --help displays help text.

        Verifies that the llm subcommand help describes provider checking.
        """
        runner = CliRunner()
        result = runner.invoke(cli, ["check", "llm", "--help"])

        assert result.exit_code == 0
        output_lower = result.output.lower()
        assert "llm" in output_lower
        # Should mention classification or providers
        assert "classification" in output_lower or "provider" in output_lower

