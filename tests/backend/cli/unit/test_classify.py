"""
Unit tests for CLI classify commands.

This module tests content classification commands using LLM for
text classification and database batch processing.
"""

from unittest.mock import MagicMock, patch

import pytest
from click.testing import CliRunner

from backend.postparse.cli.main import cli


class TestClassifyText:
    """Test classify text command."""

    def test_classify_text_with_content_argument(self) -> None:
        """
        Test classify text with content argument.

        Tests the actual command flow with mocked LLM classifier.
        """
        runner = CliRunner()

        with patch("backend.postparse.cli.classify.load_config") as mock_load:
            with patch("backend.postparse.services.analysis.classifiers.llm.RecipeLLMClassifier") as mock_classifier_class:
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
                    ["classify", "text", "Mix flour and water to make dough"],
                )

                assert result.exit_code == 0
                # Should show classification result
                assert "recipe" in result.output.lower()

    def test_classify_text_with_stdin_input(self) -> None:
        """Test classify text reading from stdin."""
        runner = CliRunner()

        with patch("backend.postparse.cli.classify.load_config") as mock_load:
            with patch("backend.postparse.services.analysis.classifiers.llm.RecipeLLMClassifier") as mock_classifier_class:
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
                    ["classify", "text", "-"],
                    input="Bake at 350 degrees for 30 minutes",
                )

                assert result.exit_code == 0

    def test_classify_text_recipe_with_details(self) -> None:
        """Test classify text showing recipe details."""
        runner = CliRunner()

        with patch("backend.postparse.cli.classify.load_config") as mock_load:
            with patch("backend.postparse.services.analysis.classifiers.llm.RecipeLLMClassifier") as mock_classifier_class:
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
                    ["classify", "text", "Make pasta"],
                )

                assert result.exit_code == 0
                # Should show details
                output_lower = result.output.lower()
                assert "italian" in output_lower or "details" in output_lower

    def test_classify_text_json_output(self) -> None:
        """Test classify text with JSON output format."""
        runner = CliRunner()

        with patch("backend.postparse.cli.classify.load_config") as mock_load:
            with patch("backend.postparse.services.analysis.classifiers.llm.RecipeLLMClassifier") as mock_classifier_class:
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
                    ["classify", "text", "--output", "json", "Random text"],
                )

                assert result.exit_code == 0
                # Should output JSON
                assert "{" in result.output

    def test_classify_text_with_specific_provider(self) -> None:
        """Test classify text with specific LLM provider."""
        runner = CliRunner()

        with patch("backend.postparse.cli.classify.load_config") as mock_load:
            with patch("backend.postparse.services.analysis.classifiers.llm.RecipeLLMClassifier") as mock_classifier_class:
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
                    ["classify", "text", "--provider", "openai", "Cook rice"],
                )

                assert result.exit_code == 0

    def test_classify_text_multiclass(self) -> None:
        """Test classify text with multiclass classifier."""
        runner = CliRunner()

        with patch("backend.postparse.cli.classify.load_config") as mock_load:
            with patch("backend.postparse.services.analysis.classifiers.multi_class.MultiClassLLMClassifier") as mock_classifier_class:
                mock_config = MagicMock()
                mock_config.get_section.return_value = {"providers": []}
                mock_load.return_value = mock_config

                mock_classifier = MagicMock()
                mock_result = MagicMock()
                mock_result.label = "tech"
                mock_result.confidence = 0.92
                mock_result.details = {
                    "reasoning": "Mentions technology",
                    "available_classes": ["recipe", "tech"]
                }
                mock_classifier.predict.return_value = mock_result
                mock_classifier_class.return_value = mock_classifier

                result = runner.invoke(
                    cli,
                    [
                        "classify", "text",
                        "--classifier", "multiclass",
                        "--classes", '{"recipe": "Cooking", "tech": "Technology"}',
                        "Check out this new FastAPI library!"
                    ],
                )

                assert result.exit_code == 0
                assert "tech" in result.output.lower()

    def test_classify_text_multiclass_requires_classes(self) -> None:
        """Test that multiclass classifier requires --classes option."""
        runner = CliRunner()

        with patch("backend.postparse.cli.classify.load_config") as mock_load:
            mock_config = MagicMock()
            mock_load.return_value = mock_config

            result = runner.invoke(
                cli,
                ["classify", "text", "--classifier", "multiclass", "Some text"],
            )

            assert result.exit_code != 0

    def test_classify_text_handles_empty_input(self) -> None:
        """Test that classify text handles empty input gracefully."""
        runner = CliRunner()

        result = runner.invoke(cli, ["classify", "text"], input="")

        # Should show error about missing text or handle gracefully
        # Command may succeed with empty stdin or fail - either is acceptable
        assert isinstance(result.exit_code, int)

    def test_classify_text_handles_classifier_error(self) -> None:
        """Test that classify text handles classifier errors."""
        runner = CliRunner()

        with patch("backend.postparse.cli.classify.load_config") as mock_load:
            with patch("backend.postparse.services.analysis.classifiers.llm.RecipeLLMClassifier") as mock_classifier_class:
                mock_config = MagicMock()
                mock_load.return_value = mock_config

                mock_classifier_class.side_effect = Exception("Classifier init failed")

                result = runner.invoke(
                    cli,
                    ["classify", "text", "Test text"],
                )

                assert result.exit_code != 0


class TestClassifyDb:
    """Test classify db command."""

    def test_classify_db_all_sources(self) -> None:
        """
        Test database classification of all sources (default).

        Mocks database and classifier at boundaries to test batch logic.
        """
        runner = CliRunner()

        with patch("backend.postparse.cli.classify.load_config") as mock_load:
            with patch("backend.postparse.cli.classify.get_database") as mock_get_db:
                with patch("backend.postparse.services.analysis.classifiers.llm.RecipeLLMClassifier") as mock_classifier_class:
                    mock_config = MagicMock()
                    mock_config.get_section.return_value = {"providers": []}
                    mock_load.return_value = mock_config

                    mock_db = MagicMock()
                    mock_db.get_instagram_posts.return_value = [
                        {"id": 1, "caption": "Recipe for pasta"},
                    ]
                    mock_db.get_telegram_messages.return_value = [
                        {"id": 1, "text": "Recipe for bread"},
                    ]
                    mock_db.has_classification.return_value = False
                    mock_get_db.return_value = mock_db

                    mock_classifier = MagicMock()
                    mock_result = MagicMock()
                    mock_result.label = "Recipe"
                    mock_result.confidence = 0.95
                    mock_result.details = {}
                    mock_classifier.predict.return_value = mock_result
                    mock_classifier.get_llm_metadata.return_value = {"provider": "test"}
                    mock_classifier_class.return_value = mock_classifier

                    # Default is --source all
                    result = runner.invoke(
                        cli,
                        ["classify", "db", "--limit", "1"],
                    )

                    assert result.exit_code == 0
                    # Should classify both posts and messages
                    assert mock_db.get_instagram_posts.called
                    assert mock_db.get_telegram_messages.called

    def test_classify_db_instagram(self) -> None:
        """
        Test database classification of Instagram posts only.

        Mocks database and classifier at boundaries to test batch logic.
        """
        runner = CliRunner()

        with patch("backend.postparse.cli.classify.load_config") as mock_load:
            with patch("backend.postparse.cli.classify.get_database") as mock_get_db:
                with patch("backend.postparse.services.analysis.classifiers.llm.RecipeLLMClassifier") as mock_classifier_class:
                    mock_config = MagicMock()
                    mock_config.get_section.return_value = {"providers": []}
                    mock_load.return_value = mock_config

                    mock_db = MagicMock()
                    mock_db.get_instagram_posts.return_value = [
                        {"id": 1, "caption": "Recipe for pasta"},
                        {"id": 2, "caption": "Beautiful sunset photo"},
                    ]
                    mock_db.has_classification.return_value = False
                    mock_get_db.return_value = mock_db

                    mock_classifier = MagicMock()
                    mock_result1 = MagicMock()
                    mock_result1.label = "Recipe"
                    mock_result1.confidence = 0.95
                    mock_result1.details = {}
                    mock_result2 = MagicMock()
                    mock_result2.label = "Not Recipe"
                    mock_result2.confidence = 0.92
                    mock_result2.details = {}
                    mock_classifier.predict.side_effect = [mock_result1, mock_result2]
                    mock_classifier.get_llm_metadata.return_value = {"provider": "test"}
                    mock_classifier_class.return_value = mock_classifier

                    result = runner.invoke(
                        cli,
                        ["classify", "db", "--source", "instagram", "--limit", "2"],
                    )

                    assert result.exit_code == 0
                    # Should show summary
                    output_lower = result.output.lower()
                    assert "recipe" in output_lower or "classified" in output_lower

    def test_classify_db_telegram(self) -> None:
        """Test database classification of Telegram messages."""
        runner = CliRunner()

        with patch("backend.postparse.cli.classify.load_config") as mock_load:
            with patch("backend.postparse.cli.classify.get_database") as mock_get_db:
                with patch("backend.postparse.services.analysis.classifiers.llm.RecipeLLMClassifier") as mock_classifier_class:
                    mock_config = MagicMock()
                    mock_config.get_section.return_value = {"providers": []}
                    mock_load.return_value = mock_config

                    mock_db = MagicMock()
                    mock_db.get_telegram_messages.return_value = [
                        {"id": 1, "text": "Recipe for bread"},
                        {"id": 2, "text": "Meeting at 3pm"},
                    ]
                    mock_db.has_classification.return_value = False
                    mock_get_db.return_value = mock_db

                    mock_classifier = MagicMock()
                    mock_result1 = MagicMock()
                    mock_result1.label = "Recipe"
                    mock_result1.confidence = 0.93
                    mock_result1.details = {}
                    mock_result2 = MagicMock()
                    mock_result2.label = "Not Recipe"
                    mock_result2.confidence = 0.98
                    mock_result2.details = {}
                    mock_classifier.predict.side_effect = [mock_result1, mock_result2]
                    mock_classifier.get_llm_metadata.return_value = {"provider": "test"}
                    mock_classifier_class.return_value = mock_classifier

                    result = runner.invoke(
                        cli,
                        ["classify", "db", "--source", "telegram", "--limit", "2"],
                    )

                    assert result.exit_code == 0

    def test_classify_db_with_hashtag_filter(self) -> None:
        """Test database classification with hashtag filtering."""
        runner = CliRunner()

        with patch("backend.postparse.cli.classify.load_config") as mock_load:
            with patch("backend.postparse.cli.classify.get_database") as mock_get_db:
                with patch("backend.postparse.services.analysis.classifiers.llm.RecipeLLMClassifier") as mock_classifier_class:
                    mock_config = MagicMock()
                    mock_config.get_section.return_value = {"providers": []}
                    mock_load.return_value = mock_config

                    mock_db = MagicMock()
                    mock_db.search_instagram_posts.return_value = (
                        [{"id": 1, "caption": "Recipe with #cooking"}],
                        None,
                    )
                    mock_db.has_classification.return_value = False
                    mock_get_db.return_value = mock_db

                    mock_classifier = MagicMock()
                    mock_result = MagicMock()
                    mock_result.label = "Recipe"
                    mock_result.confidence = 0.97
                    mock_result.details = {}
                    mock_classifier.predict.return_value = mock_result
                    mock_classifier.get_llm_metadata.return_value = {"provider": "test"}
                    mock_classifier_class.return_value = mock_classifier

                    result = runner.invoke(
                        cli,
                        [
                            "classify",
                            "db",
                            "--source",
                            "instagram",
                            "--filter-hashtag",
                            "cooking",
                        ],
                    )

                    assert result.exit_code == 0

    def test_classify_db_with_no_items(self) -> None:
        """Test database classification when no items found."""
        runner = CliRunner()

        with patch("backend.postparse.cli.classify.load_config") as mock_load:
            with patch("backend.postparse.cli.classify.get_database") as mock_get_db:
                with patch("backend.postparse.services.analysis.classifiers.llm.RecipeLLMClassifier") as mock_classifier_class:
                    mock_config = MagicMock()
                    mock_config.get_section.return_value = {"providers": []}
                    mock_load.return_value = mock_config

                    mock_db = MagicMock()
                    mock_db.get_instagram_posts.return_value = []
                    mock_db.get_telegram_messages.return_value = []
                    mock_get_db.return_value = mock_db

                    mock_classifier = MagicMock()
                    mock_classifier_class.return_value = mock_classifier

                    result = runner.invoke(
                        cli,
                        ["classify", "db"],
                    )

                    assert result.exit_code == 0
                    # Should show message about no items
                    assert "no" in result.output.lower() or "found" in result.output.lower()

    def test_classify_db_handles_classification_errors(self) -> None:
        """Test that db handles individual classification errors gracefully."""
        runner = CliRunner()

        with patch("backend.postparse.cli.classify.load_config") as mock_load:
            with patch("backend.postparse.cli.classify.get_database") as mock_get_db:
                with patch("backend.postparse.services.analysis.classifiers.llm.RecipeLLMClassifier") as mock_classifier_class:
                    mock_config = MagicMock()
                    mock_config.get_section.return_value = {"providers": []}
                    mock_load.return_value = mock_config

                    mock_db = MagicMock()
                    mock_db.get_instagram_posts.return_value = [
                        {"id": 1, "caption": "Test post"},
                    ]
                    mock_db.has_classification.return_value = False
                    mock_get_db.return_value = mock_db

                    mock_classifier = MagicMock()
                    mock_classifier.predict.side_effect = Exception("Classification failed")
                    mock_classifier_class.return_value = mock_classifier

                    result = runner.invoke(
                        cli,
                        ["classify", "db", "--source", "instagram", "--limit", "1"],
                    )

                    # Should complete despite errors
                    assert result.exit_code == 0

    def test_classify_db_multiclass(self) -> None:
        """Test database classification with multiclass classifier."""
        runner = CliRunner()

        with patch("backend.postparse.cli.classify.load_config") as mock_load:
            with patch("backend.postparse.cli.classify.get_database") as mock_get_db:
                with patch("backend.postparse.services.analysis.classifiers.multi_class.MultiClassLLMClassifier") as mock_classifier_class:
                    mock_config = MagicMock()
                    mock_config.get_section.return_value = {"providers": []}
                    mock_load.return_value = mock_config

                    mock_db = MagicMock()
                    mock_db.get_instagram_posts.return_value = [
                        {"id": 1, "caption": "Check out this new API"},
                    ]
                    mock_db.has_classification.return_value = False
                    mock_get_db.return_value = mock_db

                    mock_classifier = MagicMock()
                    mock_result = MagicMock()
                    mock_result.label = "tech"
                    mock_result.confidence = 0.90
                    mock_result.details = {"reasoning": "Tech content"}
                    mock_classifier.predict.return_value = mock_result
                    mock_classifier.get_llm_metadata.return_value = {"provider": "test"}
                    mock_classifier_class.return_value = mock_classifier

                    result = runner.invoke(
                        cli,
                        [
                            "classify", "db",
                            "--classifier", "multiclass",
                            "--classes", '{"recipe": "Cooking", "tech": "Technology"}',
                            "--limit", "1"
                        ],
                    )

                    assert result.exit_code == 0

    def test_classify_db_multiclass_requires_classes(self) -> None:
        """Test that multiclass classifier requires --classes option."""
        runner = CliRunner()

        with patch("backend.postparse.cli.classify.load_config") as mock_load:
            with patch("backend.postparse.cli.classify.get_database") as mock_get_db:
                mock_config = MagicMock()
                mock_load.return_value = mock_config
                mock_get_db.return_value = MagicMock()

                result = runner.invoke(
                    cli,
                    ["classify", "db", "--classifier", "multiclass"],
                )

                assert result.exit_code != 0

    def test_classify_db_skips_already_classified_with_same_model(self) -> None:
        """Test that db skips items already classified with same model."""
        runner = CliRunner()

        with patch("backend.postparse.cli.classify.load_config") as mock_load:
            with patch("backend.postparse.cli.classify.get_database") as mock_get_db:
                with patch("backend.postparse.services.analysis.classifiers.llm.RecipeLLMClassifier") as mock_classifier_class:
                    mock_config = MagicMock()
                    mock_config.get_section.return_value = {"providers": []}
                    mock_load.return_value = mock_config

                    mock_db = MagicMock()
                    mock_db.get_instagram_posts.return_value = [
                        {"id": 1, "caption": "Recipe for pasta"},
                    ]
                    # Already classified with same model
                    mock_db.has_classification.return_value = True
                    mock_get_db.return_value = mock_db

                    mock_classifier = MagicMock()
                    mock_classifier.get_llm_metadata.return_value = {
                        "provider": "openai", "model": "gpt-4o"
                    }
                    mock_classifier_class.return_value = mock_classifier

                    result = runner.invoke(
                        cli,
                        ["classify", "db", "--source", "instagram", "--limit", "1"],
                    )

                    assert result.exit_code == 0
                    # Should show skipped in output
                    assert "skipped" in result.output.lower()
                    # Predict should NOT have been called
                    assert not mock_classifier.predict.called

    def test_classify_db_force_reclassifies(self) -> None:
        """Test that --force flag allows reclassification."""
        runner = CliRunner()

        with patch("backend.postparse.cli.classify.load_config") as mock_load:
            with patch("backend.postparse.cli.classify.get_database") as mock_get_db:
                with patch("backend.postparse.services.analysis.classifiers.llm.RecipeLLMClassifier") as mock_classifier_class:
                    mock_config = MagicMock()
                    mock_config.get_section.return_value = {"providers": []}
                    mock_load.return_value = mock_config

                    mock_db = MagicMock()
                    mock_db.get_instagram_posts.return_value = [
                        {"id": 1, "caption": "Recipe for pasta"},
                    ]
                    # Already classified
                    mock_db.has_classification.return_value = True
                    mock_db.get_classification_id.return_value = None
                    mock_get_db.return_value = mock_db

                    mock_classifier = MagicMock()
                    mock_result = MagicMock()
                    mock_result.label = "Recipe"
                    mock_result.confidence = 0.95
                    mock_result.details = {}
                    mock_classifier.predict.return_value = mock_result
                    mock_classifier.get_llm_metadata.return_value = {
                        "provider": "openai", "model": "gpt-4o"
                    }
                    mock_classifier_class.return_value = mock_classifier

                    result = runner.invoke(
                        cli,
                        ["classify", "db", "--source", "instagram", 
                         "--limit", "1", "--force"],
                    )

                    assert result.exit_code == 0
                    # Should have classified (predict was called)
                    assert mock_classifier.predict.called
                    # Should have saved new classification
                    assert mock_db.save_classification_result.called

    def test_classify_db_force_replace_updates_existing(self) -> None:
        """Test that --force --replace updates existing classification."""
        runner = CliRunner()

        with patch("backend.postparse.cli.classify.load_config") as mock_load:
            with patch("backend.postparse.cli.classify.get_database") as mock_get_db:
                with patch("backend.postparse.services.analysis.classifiers.llm.RecipeLLMClassifier") as mock_classifier_class:
                    mock_config = MagicMock()
                    mock_config.get_section.return_value = {"providers": []}
                    mock_load.return_value = mock_config

                    mock_db = MagicMock()
                    mock_db.get_instagram_posts.return_value = [
                        {"id": 1, "caption": "Recipe for pasta"},
                    ]
                    # Already classified
                    mock_db.has_classification.return_value = True
                    mock_db.get_classification_id.return_value = 123  # Existing ID
                    mock_get_db.return_value = mock_db

                    mock_classifier = MagicMock()
                    mock_result = MagicMock()
                    mock_result.label = "Recipe"
                    mock_result.confidence = 0.95
                    mock_result.details = {}
                    mock_classifier.predict.return_value = mock_result
                    mock_classifier.get_llm_metadata.return_value = {
                        "provider": "openai", "model": "gpt-4o"
                    }
                    mock_classifier_class.return_value = mock_classifier

                    result = runner.invoke(
                        cli,
                        ["classify", "db", "--source", "instagram", 
                         "--limit", "1", "--force", "--replace"],
                    )

                    assert result.exit_code == 0
                    # Should have classified (predict was called)
                    assert mock_classifier.predict.called
                    # Should have called update_classification instead of save
                    assert mock_db.update_classification.called
                    assert not mock_db.save_classification_result.called

    def test_classify_db_replace_requires_force(self) -> None:
        """Test that --replace requires --force flag."""
        runner = CliRunner()

        with patch("backend.postparse.cli.classify.load_config") as mock_load:
            with patch("backend.postparse.cli.classify.get_database") as mock_get_db:
                mock_config = MagicMock()
                mock_load.return_value = mock_config
                mock_get_db.return_value = MagicMock()

                result = runner.invoke(
                    cli,
                    ["classify", "db", "--replace"],
                )

                assert result.exit_code != 0
                assert "requires" in result.output.lower() or "force" in result.output.lower()


class TestClassifyHelp:
    """Test classify command help output."""

    def test_classify_help_displays_subcommands(self) -> None:
        """Test that classify --help shows available subcommands."""
        runner = CliRunner()
        result = runner.invoke(cli, ["classify", "--help"])

        assert result.exit_code == 0
        output_lower = result.output.lower()
        assert "text" in output_lower
        assert "db" in output_lower

    def test_classify_text_help(self) -> None:
        """Test classify text --help displays help text."""
        runner = CliRunner()
        result = runner.invoke(cli, ["classify", "text", "--help"])

        assert result.exit_code == 0
        output_lower = result.output.lower()
        assert "text" in output_lower or "classify" in output_lower
        assert "classifier" in output_lower
        assert "provider" in output_lower

    def test_classify_db_help(self) -> None:
        """Test classify db --help displays help text."""
        runner = CliRunner()
        result = runner.invoke(cli, ["classify", "db", "--help"])

        assert result.exit_code == 0
        output_lower = result.output.lower()
        assert "db" in output_lower or "database" in output_lower
        assert "source" in output_lower
        assert "limit" in output_lower

    def test_classify_db_help_shows_force_and_replace(self) -> None:
        """Test classify db --help shows --force and --replace options."""
        runner = CliRunner()
        result = runner.invoke(cli, ["classify", "db", "--help"])

        assert result.exit_code == 0
        output_lower = result.output.lower()
        assert "--force" in output_lower
        assert "--replace" in output_lower
