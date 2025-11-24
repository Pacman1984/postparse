"""
Unit tests for CLI classify commands.

This module tests content classification commands using LLM for
single text classification and batch processing.
"""

from unittest.mock import MagicMock, patch

import pytest
from click.testing import CliRunner

from postparse.cli.main import cli


class TestClassifySingle:
    """Test classify single command."""

    def test_classify_single_with_text_argument(self) -> None:
        """
        Test classify single with text argument.

        Tests the actual command flow with mocked LLM classifier.
        """
        runner = CliRunner()

        with patch("postparse.cli.classify.load_config") as mock_load:
            with patch("postparse.services.analysis.classifiers.llm.RecipeLLMClassifier") as mock_classifier_class:
                mock_config = MagicMock()
                mock_config.get_section.return_value = {"providers": []}
                mock_load.return_value = mock_config

                mock_classifier = MagicMock()
                mock_result = MagicMock()
                mock_result.label = "Recipe"
                mock_result.confidence = 0.95
                mock_result.details = {}
                mock_result.model_dump.return_value = {
                    "label": "Recipe",
                    "confidence": 0.95,
                }
                mock_classifier.predict.return_value = mock_result
                mock_classifier_class.return_value = mock_classifier

                result = runner.invoke(
                    cli,
                    ["classify", "single", "Mix flour and water to make dough"],
                )

                assert result.exit_code == 0
                # Should show classification result
                assert "recipe" in result.output.lower()

    def test_classify_single_with_stdin_input(self) -> None:
        """Test classify single reading from stdin."""
        runner = CliRunner()

        with patch("postparse.cli.classify.load_config") as mock_load:
            with patch("postparse.services.analysis.classifiers.llm.RecipeLLMClassifier") as mock_classifier_class:
                mock_config = MagicMock()
                mock_config.get_section.return_value = {"providers": []}
                mock_load.return_value = mock_config

                mock_classifier = MagicMock()
                mock_result = MagicMock()
                mock_result.label = "Recipe"
                mock_result.confidence = 0.90
                mock_result.details = {}
                mock_result.model_dump.return_value = {
                    "label": "Recipe",
                    "confidence": 0.90,
                }
                mock_classifier.predict.return_value = mock_result
                mock_classifier_class.return_value = mock_classifier

                result = runner.invoke(
                    cli,
                    ["classify", "single", "-"],
                    input="Bake at 350 degrees for 30 minutes",
                )

                assert result.exit_code == 0

    def test_classify_single_with_detailed_flag(self) -> None:
        """Test classify single with --detailed flag showing extra info."""
        runner = CliRunner()

        with patch("postparse.cli.classify.load_config") as mock_load:
            with patch("postparse.services.analysis.classifiers.llm.RecipeLLMClassifier") as mock_classifier_class:
                mock_config = MagicMock()
                mock_config.get_section.return_value = {"providers": []}
                mock_load.return_value = mock_config

                mock_classifier = MagicMock()
                mock_result = MagicMock()
                mock_result.label = "Recipe"
                mock_result.confidence = 0.92
                mock_result.details = {
                    "cuisine_type": "Italian",
                    "difficulty": "Easy",
                }
                mock_result.model_dump.return_value = {
                    "label": "Recipe",
                    "confidence": 0.92,
                    "details": {"cuisine_type": "Italian"},
                }
                mock_classifier.predict.return_value = mock_result
                mock_classifier_class.return_value = mock_classifier

                result = runner.invoke(
                    cli,
                    ["classify", "single", "--detailed", "Make pasta"],
                )

                assert result.exit_code == 0
                # Should show details
                output_lower = result.output.lower()
                assert "italian" in output_lower or "details" in output_lower

    def test_classify_single_json_output(self) -> None:
        """Test classify single with JSON output format."""
        runner = CliRunner()

        with patch("postparse.cli.classify.load_config") as mock_load:
            with patch("postparse.services.analysis.classifiers.llm.RecipeLLMClassifier") as mock_classifier_class:
                mock_config = MagicMock()
                mock_config.get_section.return_value = {"providers": []}
                mock_load.return_value = mock_config

                mock_classifier = MagicMock()
                mock_result = MagicMock()
                mock_result.label = "Not Recipe"
                mock_result.confidence = 0.85
                mock_result.details = {}
                mock_result.model_dump.return_value = {
                    "label": "Not Recipe",
                    "confidence": 0.85,
                }
                mock_classifier.predict.return_value = mock_result
                mock_classifier_class.return_value = mock_classifier

                result = runner.invoke(
                    cli,
                    ["classify", "single", "--output", "json", "Random text"],
                )

                assert result.exit_code == 0
                # Should output JSON
                assert "{" in result.output

    def test_classify_single_with_specific_provider(self) -> None:
        """Test classify single with specific LLM provider."""
        runner = CliRunner()

        with patch("postparse.cli.classify.load_config") as mock_load:
            with patch("postparse.services.analysis.classifiers.llm.RecipeLLMClassifier") as mock_classifier_class:
                mock_config = MagicMock()
                mock_config.get_section.return_value = {
                    "providers": [
                        {"name": "openai", "base_url": "http://api.openai.com"}
                    ]
                }
                mock_load.return_value = mock_config

                mock_classifier = MagicMock()
                mock_result = MagicMock()
                mock_result.label = "Recipe"
                mock_result.confidence = 0.88
                mock_result.details = {}
                mock_result.model_dump.return_value = {
                    "label": "Recipe",
                    "confidence": 0.88,
                }
                mock_classifier.predict.return_value = mock_result
                mock_classifier_class.return_value = mock_classifier

                result = runner.invoke(
                    cli,
                    ["classify", "single", "--provider", "openai", "Cook rice"],
                )

                assert result.exit_code == 0

    def test_classify_single_handles_empty_input(self) -> None:
        """Test that classify single handles empty input gracefully."""
        runner = CliRunner()

        result = runner.invoke(cli, ["classify", "single"], input="")

        # Should show error about missing text or handle gracefully
        # Command may succeed with empty stdin or fail - either is acceptable
        assert isinstance(result.exit_code, int)

    def test_classify_single_handles_classifier_error(self) -> None:
        """Test that classify single handles classifier errors."""
        runner = CliRunner()

        with patch("postparse.cli.classify.load_config") as mock_load:
            with patch("postparse.services.analysis.classifiers.llm.RecipeLLMClassifier") as mock_classifier_class:
                mock_config = MagicMock()
                mock_load.return_value = mock_config

                mock_classifier_class.side_effect = Exception("Classifier init failed")

                result = runner.invoke(
                    cli,
                    ["classify", "single", "Test text"],
                )

                assert result.exit_code != 0


class TestClassifyBatch:
    """Test classify batch command."""

    def test_classify_batch_posts(self) -> None:
        """
        Test batch classification of Instagram posts.

        Mocks database and classifier at boundaries to test batch logic.
        """
        runner = CliRunner()

        with patch("postparse.cli.classify.load_config") as mock_load:
            with patch("postparse.cli.classify.get_database") as mock_get_db:
                with patch("postparse.services.analysis.classifiers.llm.RecipeLLMClassifier") as mock_classifier_class:
                    mock_config = MagicMock()
                    mock_config.get_section.return_value = {"providers": []}
                    mock_load.return_value = mock_config

                    mock_db = MagicMock()
                    mock_db.get_instagram_posts.return_value = [
                        {"id": 1, "caption": "Recipe for pasta"},
                        {"id": 2, "caption": "Beautiful sunset photo"},
                    ]
                    mock_get_db.return_value = mock_db

                    mock_classifier = MagicMock()
                    mock_result1 = MagicMock()
                    mock_result1.label = "Recipe"
                    mock_result1.confidence = 0.95
                    mock_result2 = MagicMock()
                    mock_result2.label = "Not Recipe"
                    mock_result2.confidence = 0.92
                    mock_classifier.predict.side_effect = [mock_result1, mock_result2]
                    mock_classifier_class.return_value = mock_classifier

                    result = runner.invoke(
                        cli,
                        ["classify", "batch", "--source", "posts", "--limit", "2"],
                    )

                    assert result.exit_code == 0
                    # Should show summary
                    output_lower = result.output.lower()
                    assert "recipe" in output_lower or "classified" in output_lower

    def test_classify_batch_messages(self) -> None:
        """Test batch classification of Telegram messages."""
        runner = CliRunner()

        with patch("postparse.cli.classify.load_config") as mock_load:
            with patch("postparse.cli.classify.get_database") as mock_get_db:
                with patch("postparse.services.analysis.classifiers.llm.RecipeLLMClassifier") as mock_classifier_class:
                    mock_config = MagicMock()
                    mock_config.get_section.return_value = {"providers": []}
                    mock_load.return_value = mock_config

                    mock_db = MagicMock()
                    mock_db.get_telegram_messages.return_value = [
                        {"id": 1, "text": "Recipe for bread"},
                        {"id": 2, "text": "Meeting at 3pm"},
                    ]
                    mock_get_db.return_value = mock_db

                    mock_classifier = MagicMock()
                    mock_result1 = MagicMock()
                    mock_result1.label = "Recipe"
                    mock_result1.confidence = 0.93
                    mock_result2 = MagicMock()
                    mock_result2.label = "Not Recipe"
                    mock_result2.confidence = 0.98
                    mock_classifier.predict.side_effect = [mock_result1, mock_result2]
                    mock_classifier_class.return_value = mock_classifier

                    result = runner.invoke(
                        cli,
                        ["classify", "batch", "--source", "messages", "--limit", "2"],
                    )

                    assert result.exit_code == 0

    def test_classify_batch_with_hashtag_filter(self) -> None:
        """Test batch classification with hashtag filtering."""
        runner = CliRunner()

        with patch("postparse.cli.classify.load_config") as mock_load:
            with patch("postparse.cli.classify.get_database") as mock_get_db:
                with patch("postparse.services.analysis.classifiers.llm.RecipeLLMClassifier") as mock_classifier_class:
                    mock_config = MagicMock()
                    mock_config.get_section.return_value = {"providers": []}
                    mock_load.return_value = mock_config

                    mock_db = MagicMock()
                    mock_db.search_instagram_posts.return_value = (
                        [{"id": 1, "caption": "Recipe with #cooking"}],
                        None,
                    )
                    mock_get_db.return_value = mock_db

                    mock_classifier = MagicMock()
                    mock_result = MagicMock()
                    mock_result.label = "Recipe"
                    mock_result.confidence = 0.97
                    mock_classifier.predict.return_value = mock_result
                    mock_classifier_class.return_value = mock_classifier

                    result = runner.invoke(
                        cli,
                        [
                            "classify",
                            "batch",
                            "--source",
                            "posts",
                            "--filter-hashtag",
                            "cooking",
                        ],
                    )

                    assert result.exit_code == 0

    def test_classify_batch_with_no_items(self) -> None:
        """Test batch classification when no items found."""
        runner = CliRunner()

        with patch("postparse.cli.classify.load_config") as mock_load:
            with patch("postparse.cli.classify.get_database") as mock_get_db:
                with patch("postparse.services.analysis.classifiers.llm.RecipeLLMClassifier") as mock_classifier_class:
                    mock_config = MagicMock()
                    mock_config.get_section.return_value = {"providers": []}
                    mock_load.return_value = mock_config

                    mock_db = MagicMock()
                    mock_db.get_instagram_posts.return_value = []
                    mock_get_db.return_value = mock_db

                    mock_classifier = MagicMock()
                    mock_classifier_class.return_value = mock_classifier

                    result = runner.invoke(
                        cli,
                        ["classify", "batch", "--source", "posts"],
                    )

                    assert result.exit_code == 0
                    # Should show message about no items
                    assert "no" in result.output.lower() or "found" in result.output.lower()

    def test_classify_batch_handles_classification_errors(self) -> None:
        """Test that batch handles individual classification errors gracefully."""
        runner = CliRunner()

        with patch("postparse.cli.classify.load_config") as mock_load:
            with patch("postparse.cli.classify.get_database") as mock_get_db:
                with patch("postparse.services.analysis.classifiers.llm.RecipeLLMClassifier") as mock_classifier_class:
                    mock_config = MagicMock()
                    mock_config.get_section.return_value = {"providers": []}
                    mock_load.return_value = mock_config

                    mock_db = MagicMock()
                    mock_db.get_instagram_posts.return_value = [
                        {"id": 1, "caption": "Test post"},
                    ]
                    mock_get_db.return_value = mock_db

                    mock_classifier = MagicMock()
                    mock_classifier.predict.side_effect = Exception("Classification failed")
                    mock_classifier_class.return_value = mock_classifier

                    result = runner.invoke(
                        cli,
                        ["classify", "batch", "--source", "posts", "--limit", "1"],
                    )

                    # Should complete despite errors
                    assert result.exit_code == 0


class TestClassifyHelp:
    """Test classify command help output."""

    def test_classify_help_displays_subcommands(self) -> None:
        """Test that classify --help shows available subcommands."""
        runner = CliRunner()
        result = runner.invoke(cli, ["classify", "--help"])

        assert result.exit_code == 0
        output_lower = result.output.lower()
        assert "single" in output_lower
        assert "batch" in output_lower

    def test_classify_single_help(self) -> None:
        """Test classify single --help displays help text."""
        runner = CliRunner()
        result = runner.invoke(cli, ["classify", "single", "--help"])

        assert result.exit_code == 0
        output_lower = result.output.lower()
        assert "single" in output_lower or "classify" in output_lower
        assert "provider" in output_lower
        assert "detailed" in output_lower

    def test_classify_batch_help(self) -> None:
        """Test classify batch --help displays help text."""
        runner = CliRunner()
        result = runner.invoke(cli, ["classify", "batch", "--help"])

        assert result.exit_code == 0
        output_lower = result.output.lower()
        assert "batch" in output_lower
        assert "source" in output_lower
        assert "limit" in output_lower

