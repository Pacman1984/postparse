"""Test the MultiClassLLMClassifier for dynamic multi-class classification.

This module provides comprehensive unit tests for the MultiClassLLMClassifier,
including initialization, prediction, batch processing, and error handling.
"""

import os
import pytest
from unittest.mock import Mock, patch, MagicMock
from langchain_core.messages import AIMessage
from langchain_litellm import ChatLiteLLM

from backend.postparse.services.analysis.classifiers import (
    MultiClassLLMClassifier,
    MultiClassResult,
    ClassificationResult,
)
from backend.postparse.llm.config import LLMConfig, ProviderConfig


# ============================================================================
# Fixtures
# ============================================================================


@pytest.fixture
def sample_classes():
    """Sample class definitions for testing.

    Returns:
        Dict mapping class names to descriptions.
    """
    return {
        "recipe": "A text containing cooking instructions, ingredients, or recipe details",
        "python_package": "A text about Python packages, libraries, or pip installations",
        "movie_review": "A text reviewing or discussing movies, films, or cinema",
    }


@pytest.fixture
def mock_multi_class_json_response():
    """Mock LLM JSON response for multi-class classification.

    Returns:
        str: JSON string representing MultiClassResult.
    """
    return '{"predicted_class": "python_package", "confidence": 0.92, "reasoning": "The text mentions FastAPI library and APIs"}'


@pytest.fixture
def mock_recipe_json_response():
    """Mock LLM JSON response for recipe classification.

    Returns:
        str: JSON string representing MultiClassResult for recipe.
    """
    return '{"predicted_class": "recipe", "confidence": 0.95, "reasoning": "Contains cooking instructions with ingredients"}'


@pytest.fixture
def mock_movie_json_response():
    """Mock LLM JSON response for movie review classification.

    Returns:
        str: JSON string representing MultiClassResult for movie review.
    """
    return '{"predicted_class": "movie_review", "confidence": 0.88, "reasoning": "The text discusses watching a movie"}'


@pytest.fixture
def mock_config_manager(sample_classes):
    """Mock ConfigManager with test configuration.

    Args:
        sample_classes: Sample class definitions.

    Returns:
        Mock: Configured ConfigManager mock.
    """
    mock_config = Mock()

    # Configure classification section with classes
    mock_config.get_section.side_effect = lambda section: {
        'classification': {
            'classes': [
                {'name': name, 'description': desc}
                for name, desc in sample_classes.items()
            ]
        },
        'llm': {
            'default_provider': 'test_provider',
            'enable_fallback': True,
            'cache_responses': False,
            'providers': [{
                'name': 'test_provider',
                'model': 'test-model',
                'api_base': 'http://localhost:1234/v1',
                'timeout': 60,
                'temperature': 0.7,
                'api_key': 'test-key'
            }]
        }
    }.get(section, {})

    mock_config.get.side_effect = lambda key, default=None: default
    mock_config.config_path = 'config/config.toml'

    return mock_config


@pytest.fixture
def mock_llm_config():
    """Mock LLMConfig with test providers.

    Returns:
        LLMConfig: Configured with test provider.
    """
    return LLMConfig(
        default_provider='test_provider',
        enable_fallback=False,
        providers=[
            ProviderConfig(
                name='test_provider',
                model='test-model',
                api_base='http://localhost:1234/v1',
                timeout=60,
                api_key='test-key',
            )
        ]
    )


# ============================================================================
# Initialization Tests
# ============================================================================


class TestMultiClassLLMClassifierInit:
    """Test cases for MultiClassLLMClassifier initialization."""

    def test_init_with_runtime_classes(self, sample_classes):
        """Test initialization with runtime class definitions."""
        os.environ.setdefault("OPENAI_API_KEY", "dummy-key-for-testing")

        with patch('backend.postparse.services.analysis.classifiers.multi_class.get_config') as mock_get_config:
            mock_config = Mock()
            mock_config.get_section.return_value = {
                'classes': [],
                'providers': [{
                    'name': 'test_provider',
                    'model': 'test-model',
                    'api_base': 'http://localhost:1234/v1',
                    'timeout': 60,
                    'temperature': 0.7,
                }]
            }
            mock_config.get.return_value = None
            mock_get_config.return_value = mock_config

            with patch('backend.postparse.services.analysis.classifiers.multi_class.LLMConfig.from_config_manager') as mock_llm:
                mock_llm.return_value = LLMConfig(
                    default_provider='test_provider',
                    enable_fallback=False,
                    providers=[ProviderConfig(
                        name='test_provider',
                        model='test-model',
                        api_base='http://localhost:1234/v1',
                        timeout=60,
                    )]
                )

                classifier = MultiClassLLMClassifier(classes=sample_classes)

                assert classifier.classes == sample_classes
                assert len(classifier.classes) == 3
                assert 'recipe' in classifier.classes
                assert 'python_package' in classifier.classes
                assert 'movie_review' in classifier.classes

    def test_init_with_config_classes(self, sample_classes, mock_config_manager):
        """Test initialization loading classes from config."""
        os.environ.setdefault("OPENAI_API_KEY", "dummy-key-for-testing")

        with patch('backend.postparse.services.analysis.classifiers.multi_class.get_config') as mock_get_config:
            mock_get_config.return_value = mock_config_manager

            with patch('backend.postparse.services.analysis.classifiers.multi_class.LLMConfig.from_config_manager') as mock_llm:
                mock_llm.return_value = LLMConfig(
                    default_provider='test_provider',
                    enable_fallback=False,
                    providers=[ProviderConfig(
                        name='test_provider',
                        model='test-model',
                        api_base='http://localhost:1234/v1',
                        timeout=60,
                    )]
                )

                classifier = MultiClassLLMClassifier()

                assert len(classifier.classes) >= 2

    def test_init_with_merged_classes(self, sample_classes, mock_config_manager):
        """Test that runtime classes override config classes."""
        os.environ.setdefault("OPENAI_API_KEY", "dummy-key-for-testing")

        runtime_classes = {
            "recipe": "Updated recipe description",  # Override
            "sports": "Sports news and scores",  # New class
        }

        with patch('backend.postparse.services.analysis.classifiers.multi_class.get_config') as mock_get_config:
            mock_get_config.return_value = mock_config_manager

            with patch('backend.postparse.services.analysis.classifiers.multi_class.LLMConfig.from_config_manager') as mock_llm:
                mock_llm.return_value = LLMConfig(
                    default_provider='test_provider',
                    enable_fallback=False,
                    providers=[ProviderConfig(
                        name='test_provider',
                        model='test-model',
                        api_base='http://localhost:1234/v1',
                        timeout=60,
                    )]
                )

                classifier = MultiClassLLMClassifier(classes=runtime_classes)

                # Runtime class should override config
                assert classifier.classes['recipe'] == "Updated recipe description"
                # New runtime class should be added
                assert 'sports' in classifier.classes

    def test_init_with_provider_name(self, sample_classes):
        """Test initialization with specific provider."""
        os.environ.setdefault("OPENAI_API_KEY", "dummy-key-for-testing")

        with patch('backend.postparse.services.analysis.classifiers.multi_class.get_config') as mock_get_config:
            mock_config = Mock()
            mock_config.get_section.return_value = {'classes': []}
            mock_config.get.return_value = None
            mock_get_config.return_value = mock_config

            with patch('backend.postparse.services.analysis.classifiers.multi_class.LLMConfig.from_config_manager') as mock_llm:
                mock_llm.return_value = LLMConfig(
                    default_provider='lm_studio',
                    enable_fallback=False,
                    providers=[
                        ProviderConfig(
                            name='lm_studio',
                            model='model-1',
                            api_base='http://localhost:1234/v1',
                            timeout=60,
                        ),
                        ProviderConfig(
                            name='openai',
                            model='gpt-4o-mini',
                            timeout=30,
                        )
                    ]
                )

                classifier = MultiClassLLMClassifier(
                    classes=sample_classes,
                    provider_name='openai'
                )

                assert classifier.llm is not None
                assert isinstance(classifier.llm, ChatLiteLLM)

    def test_init_fails_with_no_classes(self):
        """Test ValueError when no classes defined."""
        os.environ.setdefault("OPENAI_API_KEY", "dummy-key-for-testing")

        with patch('backend.postparse.services.analysis.classifiers.multi_class.get_config') as mock_get_config:
            mock_config = Mock()
            mock_config.get_section.return_value = {'classes': []}
            mock_config.get.return_value = None
            mock_get_config.return_value = mock_config

            with patch('backend.postparse.services.analysis.classifiers.multi_class.LLMConfig.from_config_manager') as mock_llm:
                mock_llm.return_value = LLMConfig(
                    default_provider='test_provider',
                    enable_fallback=False,
                    providers=[ProviderConfig(
                        name='test_provider',
                        model='test-model',
                        timeout=60,
                    )]
                )

                with pytest.raises(ValueError, match="At least 2 classes are required"):
                    MultiClassLLMClassifier(classes={})

    def test_init_fails_with_single_class(self):
        """Test ValueError when only 1 class defined."""
        os.environ.setdefault("OPENAI_API_KEY", "dummy-key-for-testing")

        with patch('backend.postparse.services.analysis.classifiers.multi_class.get_config') as mock_get_config:
            mock_config = Mock()
            mock_config.get_section.return_value = {'classes': []}
            mock_config.get.return_value = None
            mock_get_config.return_value = mock_config

            with patch('backend.postparse.services.analysis.classifiers.multi_class.LLMConfig.from_config_manager') as mock_llm:
                mock_llm.return_value = LLMConfig(
                    default_provider='test_provider',
                    enable_fallback=False,
                    providers=[ProviderConfig(
                        name='test_provider',
                        model='test-model',
                        timeout=60,
                    )]
                )

                with pytest.raises(ValueError, match="At least 2 classes are required"):
                    MultiClassLLMClassifier(classes={"only_one": "Single class"})


# ============================================================================
# Prediction Tests
# ============================================================================


class TestMultiClassLLMClassifierPredict:
    """Test cases for MultiClassLLMClassifier.predict()."""

    def test_predict_python_package(
        self,
        sample_classes,
        mock_multi_class_json_response,
        mock_config_manager
    ):
        """Test classifying a Python package text."""
        os.environ.setdefault("OPENAI_API_KEY", "dummy-key-for-testing")

        with patch('backend.postparse.services.analysis.classifiers.multi_class.get_config') as mock_get_config:
            mock_get_config.return_value = mock_config_manager

            with patch('backend.postparse.services.analysis.classifiers.multi_class.LLMConfig.from_config_manager') as mock_llm_config:
                mock_llm_config.return_value = LLMConfig(
                    default_provider='test_provider',
                    enable_fallback=False,
                    providers=[ProviderConfig(
                        name='test_provider',
                        model='test-model',
                        api_base='http://localhost:1234/v1',
                        timeout=60,
                    )]
                )

                with patch('backend.postparse.services.analysis.classifiers.multi_class.ChatLiteLLM') as mock_chat:
                    mock_instance = Mock()
                    mock_instance.invoke.return_value = AIMessage(content=mock_multi_class_json_response)
                    mock_chat.return_value = mock_instance

                    classifier = MultiClassLLMClassifier(classes=sample_classes)
                    result = classifier.predict("Check out this new FastAPI library!")

                    assert isinstance(result, ClassificationResult)
                    assert result.label == "python_package"
                    assert result.confidence == 0.92
                    assert 'reasoning' in result.details
                    assert 'available_classes' in result.details

    def test_predict_recipe(
        self,
        sample_classes,
        mock_recipe_json_response,
        mock_config_manager
    ):
        """Test classifying a recipe text."""
        os.environ.setdefault("OPENAI_API_KEY", "dummy-key-for-testing")

        with patch('backend.postparse.services.analysis.classifiers.multi_class.get_config') as mock_get_config:
            mock_get_config.return_value = mock_config_manager

            with patch('backend.postparse.services.analysis.classifiers.multi_class.LLMConfig.from_config_manager') as mock_llm_config:
                mock_llm_config.return_value = LLMConfig(
                    default_provider='test_provider',
                    enable_fallback=False,
                    providers=[ProviderConfig(
                        name='test_provider',
                        model='test-model',
                        api_base='http://localhost:1234/v1',
                        timeout=60,
                    )]
                )

                with patch('backend.postparse.services.analysis.classifiers.multi_class.ChatLiteLLM') as mock_chat:
                    mock_instance = Mock()
                    mock_instance.invoke.return_value = AIMessage(content=mock_recipe_json_response)
                    mock_chat.return_value = mock_instance

                    classifier = MultiClassLLMClassifier(classes=sample_classes)
                    result = classifier.predict("Boil pasta for 10 minutes, add sauce")

                    assert result.label == "recipe"
                    assert result.confidence == 0.95

    def test_predict_movie_review(
        self,
        sample_classes,
        mock_movie_json_response,
        mock_config_manager
    ):
        """Test classifying a movie review text."""
        os.environ.setdefault("OPENAI_API_KEY", "dummy-key-for-testing")

        with patch('backend.postparse.services.analysis.classifiers.multi_class.get_config') as mock_get_config:
            mock_get_config.return_value = mock_config_manager

            with patch('backend.postparse.services.analysis.classifiers.multi_class.LLMConfig.from_config_manager') as mock_llm_config:
                mock_llm_config.return_value = LLMConfig(
                    default_provider='test_provider',
                    enable_fallback=False,
                    providers=[ProviderConfig(
                        name='test_provider',
                        model='test-model',
                        api_base='http://localhost:1234/v1',
                        timeout=60,
                    )]
                )

                with patch('backend.postparse.services.analysis.classifiers.multi_class.ChatLiteLLM') as mock_chat:
                    mock_instance = Mock()
                    mock_instance.invoke.return_value = AIMessage(content=mock_movie_json_response)
                    mock_chat.return_value = mock_instance

                    classifier = MultiClassLLMClassifier(classes=sample_classes)
                    result = classifier.predict("Just watched an amazing thriller!")

                    assert result.label == "movie_review"
                    assert result.confidence == 0.88

    def test_predict_with_confidence_in_range(
        self,
        sample_classes,
        mock_multi_class_json_response,
        mock_config_manager
    ):
        """Test that confidence scores are in valid range (0.0-1.0)."""
        os.environ.setdefault("OPENAI_API_KEY", "dummy-key-for-testing")

        with patch('backend.postparse.services.analysis.classifiers.multi_class.get_config') as mock_get_config:
            mock_get_config.return_value = mock_config_manager

            with patch('backend.postparse.services.analysis.classifiers.multi_class.LLMConfig.from_config_manager') as mock_llm_config:
                mock_llm_config.return_value = LLMConfig(
                    default_provider='test_provider',
                    enable_fallback=False,
                    providers=[ProviderConfig(
                        name='test_provider',
                        model='test-model',
                        api_base='http://localhost:1234/v1',
                        timeout=60,
                    )]
                )

                with patch('backend.postparse.services.analysis.classifiers.multi_class.ChatLiteLLM') as mock_chat:
                    mock_instance = Mock()
                    mock_instance.invoke.return_value = AIMessage(content=mock_multi_class_json_response)
                    mock_chat.return_value = mock_instance

                    classifier = MultiClassLLMClassifier(classes=sample_classes)
                    result = classifier.predict("Test text")

                    assert 0.0 <= result.confidence <= 1.0

    def test_predict_with_reasoning_in_details(
        self,
        sample_classes,
        mock_multi_class_json_response,
        mock_config_manager
    ):
        """Test that reasoning is included in details."""
        os.environ.setdefault("OPENAI_API_KEY", "dummy-key-for-testing")

        with patch('backend.postparse.services.analysis.classifiers.multi_class.get_config') as mock_get_config:
            mock_get_config.return_value = mock_config_manager

            with patch('backend.postparse.services.analysis.classifiers.multi_class.LLMConfig.from_config_manager') as mock_llm_config:
                mock_llm_config.return_value = LLMConfig(
                    default_provider='test_provider',
                    enable_fallback=False,
                    providers=[ProviderConfig(
                        name='test_provider',
                        model='test-model',
                        api_base='http://localhost:1234/v1',
                        timeout=60,
                    )]
                )

                with patch('backend.postparse.services.analysis.classifiers.multi_class.ChatLiteLLM') as mock_chat:
                    mock_instance = Mock()
                    mock_instance.invoke.return_value = AIMessage(content=mock_multi_class_json_response)
                    mock_chat.return_value = mock_instance

                    classifier = MultiClassLLMClassifier(classes=sample_classes)
                    result = classifier.predict("Test text")

                    assert result.details is not None
                    assert 'reasoning' in result.details
                    assert result.details['reasoning'] == "The text mentions FastAPI library and APIs"

    def test_predict_with_available_classes_in_details(
        self,
        sample_classes,
        mock_multi_class_json_response,
        mock_config_manager
    ):
        """Test that available_classes is in details."""
        os.environ.setdefault("OPENAI_API_KEY", "dummy-key-for-testing")

        with patch('backend.postparse.services.analysis.classifiers.multi_class.get_config') as mock_get_config:
            mock_get_config.return_value = mock_config_manager

            with patch('backend.postparse.services.analysis.classifiers.multi_class.LLMConfig.from_config_manager') as mock_llm_config:
                mock_llm_config.return_value = LLMConfig(
                    default_provider='test_provider',
                    enable_fallback=False,
                    providers=[ProviderConfig(
                        name='test_provider',
                        model='test-model',
                        api_base='http://localhost:1234/v1',
                        timeout=60,
                    )]
                )

                with patch('backend.postparse.services.analysis.classifiers.multi_class.ChatLiteLLM') as mock_chat:
                    mock_instance = Mock()
                    mock_instance.invoke.return_value = AIMessage(content=mock_multi_class_json_response)
                    mock_chat.return_value = mock_instance

                    classifier = MultiClassLLMClassifier(classes=sample_classes)
                    result = classifier.predict("Test text")

                    assert result.details is not None
                    assert 'available_classes' in result.details
                    assert set(result.details['available_classes']) == set(sample_classes.keys())

    def test_predict_invalid_class_from_llm(
        self,
        sample_classes,
        mock_config_manager
    ):
        """Test error handling when LLM returns invalid class."""
        os.environ.setdefault("OPENAI_API_KEY", "dummy-key-for-testing")

        invalid_response = '{"predicted_class": "invalid_class", "confidence": 0.8, "reasoning": "Test"}'

        with patch('backend.postparse.services.analysis.classifiers.multi_class.get_config') as mock_get_config:
            mock_get_config.return_value = mock_config_manager

            with patch('backend.postparse.services.analysis.classifiers.multi_class.LLMConfig.from_config_manager') as mock_llm_config:
                mock_llm_config.return_value = LLMConfig(
                    default_provider='test_provider',
                    enable_fallback=False,
                    providers=[ProviderConfig(
                        name='test_provider',
                        model='test-model',
                        api_base='http://localhost:1234/v1',
                        timeout=60,
                    )]
                )

                with patch('backend.postparse.services.analysis.classifiers.multi_class.ChatLiteLLM') as mock_chat:
                    mock_instance = Mock()
                    mock_instance.invoke.return_value = AIMessage(content=invalid_response)
                    mock_chat.return_value = mock_instance

                    classifier = MultiClassLLMClassifier(classes=sample_classes)

                    with pytest.raises(ValueError, match="LLM returned invalid class"):
                        classifier.predict("Test text")


# ============================================================================
# Batch Prediction Tests
# ============================================================================


class TestMultiClassLLMClassifierBatch:
    """Test cases for batch prediction."""

    def test_predict_batch(
        self,
        sample_classes,
        mock_recipe_json_response,
        mock_multi_class_json_response,
        mock_movie_json_response,
        mock_config_manager
    ):
        """Test batch prediction with multiple texts."""
        os.environ.setdefault("OPENAI_API_KEY", "dummy-key-for-testing")

        with patch('backend.postparse.services.analysis.classifiers.multi_class.get_config') as mock_get_config:
            mock_get_config.return_value = mock_config_manager

            with patch('backend.postparse.services.analysis.classifiers.multi_class.LLMConfig.from_config_manager') as mock_llm_config:
                mock_llm_config.return_value = LLMConfig(
                    default_provider='test_provider',
                    enable_fallback=False,
                    providers=[ProviderConfig(
                        name='test_provider',
                        model='test-model',
                        api_base='http://localhost:1234/v1',
                        timeout=60,
                    )]
                )

                with patch('backend.postparse.services.analysis.classifiers.multi_class.ChatLiteLLM') as mock_chat:
                    mock_instance = Mock()
                    mock_instance.invoke.side_effect = [
                        AIMessage(content=mock_recipe_json_response),
                        AIMessage(content=mock_multi_class_json_response),
                        AIMessage(content=mock_movie_json_response),
                    ]
                    mock_chat.return_value = mock_instance

                    classifier = MultiClassLLMClassifier(classes=sample_classes)
                    texts = [
                        "Boil pasta for 10 minutes",
                        "Check out FastAPI library",
                        "Great movie last night"
                    ]
                    results = classifier.predict_batch(texts)

                    assert len(results) == 3
                    assert results[0].label == "recipe"
                    assert results[1].label == "python_package"
                    assert results[2].label == "movie_review"

    def test_predict_batch_empty_list(
        self,
        sample_classes,
        mock_config_manager
    ):
        """Test batch prediction with empty list."""
        os.environ.setdefault("OPENAI_API_KEY", "dummy-key-for-testing")

        with patch('backend.postparse.services.analysis.classifiers.multi_class.get_config') as mock_get_config:
            mock_get_config.return_value = mock_config_manager

            with patch('backend.postparse.services.analysis.classifiers.multi_class.LLMConfig.from_config_manager') as mock_llm_config:
                mock_llm_config.return_value = LLMConfig(
                    default_provider='test_provider',
                    enable_fallback=False,
                    providers=[ProviderConfig(
                        name='test_provider',
                        model='test-model',
                        api_base='http://localhost:1234/v1',
                        timeout=60,
                    )]
                )

                with patch('backend.postparse.services.analysis.classifiers.multi_class.ChatLiteLLM') as mock_chat:
                    mock_chat.return_value = Mock()

                    classifier = MultiClassLLMClassifier(classes=sample_classes)
                    results = classifier.predict_batch([])

                    assert len(results) == 0


# ============================================================================
# Utility Method Tests
# ============================================================================


class TestMultiClassLLMClassifierUtilities:
    """Test cases for utility methods."""

    def test_fit_returns_self(
        self,
        sample_classes,
        mock_config_manager
    ):
        """Test fit method returns self (no-op for LLM classifiers)."""
        os.environ.setdefault("OPENAI_API_KEY", "dummy-key-for-testing")

        with patch('backend.postparse.services.analysis.classifiers.multi_class.get_config') as mock_get_config:
            mock_get_config.return_value = mock_config_manager

            with patch('backend.postparse.services.analysis.classifiers.multi_class.LLMConfig.from_config_manager') as mock_llm_config:
                mock_llm_config.return_value = LLMConfig(
                    default_provider='test_provider',
                    enable_fallback=False,
                    providers=[ProviderConfig(
                        name='test_provider',
                        model='test-model',
                        api_base='http://localhost:1234/v1',
                        timeout=60,
                    )]
                )

                with patch('backend.postparse.services.analysis.classifiers.multi_class.ChatLiteLLM'):
                    classifier = MultiClassLLMClassifier(classes=sample_classes)
                    result = classifier.fit([], [])

                    assert result is classifier

    def test_get_classes(
        self,
        sample_classes,
        mock_config_manager
    ):
        """Test get_classes returns copy of classes dict."""
        os.environ.setdefault("OPENAI_API_KEY", "dummy-key-for-testing")

        with patch('backend.postparse.services.analysis.classifiers.multi_class.get_config') as mock_get_config:
            mock_get_config.return_value = mock_config_manager

            with patch('backend.postparse.services.analysis.classifiers.multi_class.LLMConfig.from_config_manager') as mock_llm_config:
                mock_llm_config.return_value = LLMConfig(
                    default_provider='test_provider',
                    enable_fallback=False,
                    providers=[ProviderConfig(
                        name='test_provider',
                        model='test-model',
                        api_base='http://localhost:1234/v1',
                        timeout=60,
                    )]
                )

                with patch('backend.postparse.services.analysis.classifiers.multi_class.ChatLiteLLM'):
                    classifier = MultiClassLLMClassifier(classes=sample_classes)
                    classes = classifier.get_classes()

                    assert classes == sample_classes
                    # Should be a copy, not the original
                    classes['new_class'] = 'test'
                    assert 'new_class' not in classifier.classes

    def test_get_class_names(
        self,
        sample_classes,
        mock_config_manager
    ):
        """Test get_class_names returns list of class names."""
        os.environ.setdefault("OPENAI_API_KEY", "dummy-key-for-testing")

        with patch('backend.postparse.services.analysis.classifiers.multi_class.get_config') as mock_get_config:
            mock_get_config.return_value = mock_config_manager

            with patch('backend.postparse.services.analysis.classifiers.multi_class.LLMConfig.from_config_manager') as mock_llm_config:
                mock_llm_config.return_value = LLMConfig(
                    default_provider='test_provider',
                    enable_fallback=False,
                    providers=[ProviderConfig(
                        name='test_provider',
                        model='test-model',
                        api_base='http://localhost:1234/v1',
                        timeout=60,
                    )]
                )

                with patch('backend.postparse.services.analysis.classifiers.multi_class.ChatLiteLLM'):
                    classifier = MultiClassLLMClassifier(classes=sample_classes)
                    class_names = classifier.get_class_names()

                    assert set(class_names) == set(sample_classes.keys())


# ============================================================================
# Model Tests
# ============================================================================


class TestMultiClassResult:
    """Test cases for MultiClassResult model."""

    def test_multi_class_result_creation(self):
        """Test creating MultiClassResult instance."""
        result = MultiClassResult(
            predicted_class="python_package",
            confidence=0.92,
            reasoning="The text mentions FastAPI library"
        )

        assert result.predicted_class == "python_package"
        assert result.confidence == 0.92
        assert result.reasoning == "The text mentions FastAPI library"

    def test_multi_class_result_without_reasoning(self):
        """Test creating MultiClassResult without reasoning."""
        result = MultiClassResult(
            predicted_class="recipe",
            confidence=0.85,
        )

        assert result.predicted_class == "recipe"
        assert result.confidence == 0.85
        assert result.reasoning is None

    def test_multi_class_result_serialization(self):
        """Test MultiClassResult model serialization."""
        result = MultiClassResult(
            predicted_class="movie_review",
            confidence=0.88,
            reasoning="Discusses watching a film"
        )

        dumped = result.model_dump()

        assert isinstance(dumped, dict)
        assert dumped['predicted_class'] == "movie_review"
        assert dumped['confidence'] == 0.88
        assert dumped['reasoning'] == "Discusses watching a film"

    def test_multi_class_result_confidence_validation(self):
        """Test confidence validation in MultiClassResult."""
        # Valid confidence
        result = MultiClassResult(
            predicted_class="test",
            confidence=0.5,
        )
        assert result.confidence == 0.5

        # Boundary values
        result_min = MultiClassResult(predicted_class="test", confidence=0.0)
        assert result_min.confidence == 0.0

        result_max = MultiClassResult(predicted_class="test", confidence=1.0)
        assert result_max.confidence == 1.0

