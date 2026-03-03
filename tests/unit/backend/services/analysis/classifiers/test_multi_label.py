"""Unit tests for MultiLabelLLMClassifier.

Tests initialization, multi-label prediction, single-label fallback,
label validation, and utility methods with mocked LLM responses.
"""

import json
import os
from typing import Dict
from unittest.mock import Mock, patch

import pytest
from langchain_core.messages import AIMessage

from backend.postparse.services.analysis.classifiers import (
    ClassificationResult,
    LabelScore,
    MultiLabelClassificationResult,
    MultiLabelLLMClassifier,
)
from backend.postparse.llm.config import LLMConfig, ProviderConfig


# ============================================================================
# Fixtures
# ============================================================================


@pytest.fixture
def sample_classes() -> Dict[str, str]:
    """Sample class definitions for testing."""
    return {
        "recipe": "Cooking or baking recipes with ingredients and steps",
        "cocktail": "Cocktail or drink recipes with mixing instructions",
        "restaurant": "Restaurant or dining recommendations",
    }


@pytest.fixture
def mock_multilabel_response() -> str:
    """Mock LLM JSON response with multiple labels."""
    return json.dumps({
        "predicted_classes": [
            {"label": "recipe", "confidence": 0.95},
            {"label": "cocktail", "confidence": 0.88},
        ],
        "reasoning": "Text contains cocktail mixing instructions with ingredients",
    })


@pytest.fixture
def mock_single_label_response() -> str:
    """Mock LLM JSON response with a single label."""
    return json.dumps({
        "predicted_classes": [
            {"label": "restaurant", "confidence": 0.92},
        ],
        "reasoning": "Text recommends a restaurant",
    })


@pytest.fixture
def mock_empty_label_response() -> str:
    """Mock LLM JSON response with no matching labels."""
    return json.dumps({
        "predicted_classes": [],
        "reasoning": "No category matches the content",
    })


@pytest.fixture
def _mock_provider() -> LLMConfig:
    """LLMConfig with a single test provider."""
    return LLMConfig(
        default_provider="test_provider",
        enable_fallback=False,
        providers=[
            ProviderConfig(
                name="test_provider",
                model="test-model",
                api_base="http://localhost:1234/v1",
                timeout=60,
            )
        ],
    )


@pytest.fixture
def mock_config_manager(sample_classes):
    """Mock ConfigManager returning sample classes and LLM config."""
    mock_config = Mock()
    mock_config.get_section.side_effect = lambda section: {
        "classification": {
            "classes": [
                {"name": n, "description": d}
                for n, d in sample_classes.items()
            ]
        },
        "llm": {
            "default_provider": "test_provider",
            "providers": [{
                "name": "test_provider",
                "model": "test-model",
                "api_base": "http://localhost:1234/v1",
                "timeout": 60,
                "temperature": 0.7,
            }],
        },
    }.get(section, {})
    mock_config.get.side_effect = lambda key, default=None: default
    mock_config.config_path = "config/config.toml"
    return mock_config


def _build_classifier(sample_classes, _mock_provider, mock_chat_cls):
    """Helper to construct a MultiLabelLLMClassifier with mocks."""
    with patch(
        "backend.postparse.services.analysis.classifiers.multi_label.get_config"
    ) as mock_get_config:
        mock_cfg = Mock()
        mock_cfg.get_section.return_value = {"classes": []}
        mock_cfg.get.return_value = None
        mock_get_config.return_value = mock_cfg

        with patch(
            "backend.postparse.services.analysis.classifiers.multi_label.LLMConfig.from_config_manager"
        ) as mock_llm:
            mock_llm.return_value = _mock_provider

            with patch(
                "backend.postparse.services.analysis.classifiers.multi_label.ChatLiteLLM",
                mock_chat_cls,
            ):
                return MultiLabelLLMClassifier(classes=sample_classes)


# ============================================================================
# Initialization Tests
# ============================================================================


class TestMultiLabelLLMClassifierInit:
    """Test MultiLabelLLMClassifier initialization."""

    def test_init_with_runtime_classes(
        self, sample_classes: Dict[str, str], _mock_provider: LLMConfig
    ) -> None:
        """Classifier stores runtime classes correctly."""
        os.environ.setdefault("OPENAI_API_KEY", "dummy")
        mock_chat = Mock()
        clf = _build_classifier(sample_classes, _mock_provider, mock_chat)

        assert clf.classes == sample_classes
        assert len(clf.classes) == 3

    def test_init_fails_with_too_few_classes(
        self, _mock_provider: LLMConfig
    ) -> None:
        """ValueError if fewer than 2 classes."""
        os.environ.setdefault("OPENAI_API_KEY", "dummy")

        with pytest.raises(ValueError, match="At least 2 classes"):
            _build_classifier({"one": "Only one"}, _mock_provider, Mock())

    def test_init_fails_with_invalid_provider(
        self, sample_classes: Dict[str, str], _mock_provider: LLMConfig
    ) -> None:
        """ValueError if explicit provider_name not in config."""
        os.environ.setdefault("OPENAI_API_KEY", "dummy")

        with patch(
            "backend.postparse.services.analysis.classifiers.multi_label.get_config"
        ) as mock_get_config:
            mock_cfg = Mock()
            mock_cfg.get_section.return_value = {"classes": []}
            mock_cfg.get.return_value = None
            mock_get_config.return_value = mock_cfg

            with patch(
                "backend.postparse.services.analysis.classifiers.multi_label.LLMConfig.from_config_manager"
            ) as mock_llm:
                mock_llm.return_value = _mock_provider

                with patch(
                    "backend.postparse.services.analysis.classifiers.multi_label.ChatLiteLLM",
                    Mock(),
                ):
                    with pytest.raises(ValueError, match="not found"):
                        MultiLabelLLMClassifier(
                            classes=sample_classes,
                            provider_name="nonexistent_provider",
                        )


# ============================================================================
# Multi-Label Prediction Tests
# ============================================================================


class TestMultiLabelPrediction:
    """Test predict_multilabel() method."""

    def test_returns_multiple_labels(
        self,
        sample_classes: Dict[str, str],
        _mock_provider: LLMConfig,
        mock_multilabel_response: str,
    ) -> None:
        """predict_multilabel returns all matching labels."""
        os.environ.setdefault("OPENAI_API_KEY", "dummy")
        mock_chat = Mock()
        mock_instance = Mock()
        mock_instance.invoke.return_value = AIMessage(
            content=mock_multilabel_response
        )
        mock_chat.return_value = mock_instance

        clf = _build_classifier(sample_classes, _mock_provider, mock_chat)
        result = clf.predict_multilabel("Mojito recipe at the beach bar")

        assert isinstance(result, MultiLabelClassificationResult)
        assert len(result.labels) == 2
        assert result.labels[0].label == "recipe"
        assert result.labels[0].confidence == 0.95
        assert result.labels[1].label == "cocktail"
        assert result.reasoning is not None

    def test_returns_single_label(
        self,
        sample_classes: Dict[str, str],
        _mock_provider: LLMConfig,
        mock_single_label_response: str,
    ) -> None:
        """predict_multilabel can return a single label."""
        os.environ.setdefault("OPENAI_API_KEY", "dummy")
        mock_chat = Mock()
        mock_instance = Mock()
        mock_instance.invoke.return_value = AIMessage(
            content=mock_single_label_response
        )
        mock_chat.return_value = mock_instance

        clf = _build_classifier(sample_classes, _mock_provider, mock_chat)
        result = clf.predict_multilabel("Best sushi place in town")

        assert len(result.labels) == 1
        assert result.labels[0].label == "restaurant"

    def test_returns_empty_labels(
        self,
        sample_classes: Dict[str, str],
        _mock_provider: LLMConfig,
        mock_empty_label_response: str,
    ) -> None:
        """predict_multilabel returns empty list when nothing matches."""
        os.environ.setdefault("OPENAI_API_KEY", "dummy")
        mock_chat = Mock()
        mock_instance = Mock()
        mock_instance.invoke.return_value = AIMessage(
            content=mock_empty_label_response
        )
        mock_chat.return_value = mock_instance

        clf = _build_classifier(sample_classes, _mock_provider, mock_chat)
        result = clf.predict_multilabel("Random unrelated text")

        assert len(result.labels) == 0
        assert result.reasoning is not None

    def test_labels_sorted_by_confidence(
        self,
        sample_classes: Dict[str, str],
        _mock_provider: LLMConfig,
    ) -> None:
        """Labels are sorted highest confidence first."""
        os.environ.setdefault("OPENAI_API_KEY", "dummy")
        response = json.dumps({
            "predicted_classes": [
                {"label": "cocktail", "confidence": 0.70},
                {"label": "recipe", "confidence": 0.95},
                {"label": "restaurant", "confidence": 0.80},
            ],
            "reasoning": "Multiple matches",
        })
        mock_chat = Mock()
        mock_instance = Mock()
        mock_instance.invoke.return_value = AIMessage(content=response)
        mock_chat.return_value = mock_instance

        clf = _build_classifier(sample_classes, _mock_provider, mock_chat)
        result = clf.predict_multilabel("test")

        confidences = [ls.confidence for ls in result.labels]
        assert confidences == sorted(confidences, reverse=True)

    def test_invalid_labels_filtered_out(
        self,
        sample_classes: Dict[str, str],
        _mock_provider: LLMConfig,
    ) -> None:
        """Invalid label names from LLM are silently dropped."""
        os.environ.setdefault("OPENAI_API_KEY", "dummy")
        response = json.dumps({
            "predicted_classes": [
                {"label": "recipe", "confidence": 0.90},
                {"label": "INVALID_CLASS", "confidence": 0.85},
            ],
            "reasoning": "test",
        })
        mock_chat = Mock()
        mock_instance = Mock()
        mock_instance.invoke.return_value = AIMessage(content=response)
        mock_chat.return_value = mock_instance

        clf = _build_classifier(sample_classes, _mock_provider, mock_chat)
        result = clf.predict_multilabel("test")

        assert len(result.labels) == 1
        assert result.labels[0].label == "recipe"

    def test_case_insensitive_label_matching(
        self,
        sample_classes: Dict[str, str],
        _mock_provider: LLMConfig,
    ) -> None:
        """Labels are matched case-insensitively."""
        os.environ.setdefault("OPENAI_API_KEY", "dummy")
        response = json.dumps({
            "predicted_classes": [
                {"label": "Recipe", "confidence": 0.90},
                {"label": "COCKTAIL", "confidence": 0.85},
            ],
            "reasoning": "test",
        })
        mock_chat = Mock()
        mock_instance = Mock()
        mock_instance.invoke.return_value = AIMessage(content=response)
        mock_chat.return_value = mock_instance

        clf = _build_classifier(sample_classes, _mock_provider, mock_chat)
        result = clf.predict_multilabel("test")

        assert len(result.labels) == 2
        assert result.labels[0].label == "recipe"
        assert result.labels[1].label == "cocktail"

    def test_available_classes_populated(
        self,
        sample_classes: Dict[str, str],
        _mock_provider: LLMConfig,
        mock_multilabel_response: str,
    ) -> None:
        """available_classes contains all configured classes."""
        os.environ.setdefault("OPENAI_API_KEY", "dummy")
        mock_chat = Mock()
        mock_instance = Mock()
        mock_instance.invoke.return_value = AIMessage(
            content=mock_multilabel_response
        )
        mock_chat.return_value = mock_instance

        clf = _build_classifier(sample_classes, _mock_provider, mock_chat)
        result = clf.predict_multilabel("test")

        assert set(result.available_classes) == set(sample_classes.keys())


# ============================================================================
# Single-Label Fallback Tests
# ============================================================================


class TestMultiLabelPredictFallback:
    """Test predict() single-label fallback."""

    def test_predict_returns_top_label(
        self,
        sample_classes: Dict[str, str],
        _mock_provider: LLMConfig,
        mock_multilabel_response: str,
    ) -> None:
        """predict() returns the highest-confidence label."""
        os.environ.setdefault("OPENAI_API_KEY", "dummy")
        mock_chat = Mock()
        mock_instance = Mock()
        mock_instance.invoke.return_value = AIMessage(
            content=mock_multilabel_response
        )
        mock_chat.return_value = mock_instance

        clf = _build_classifier(sample_classes, _mock_provider, mock_chat)
        result = clf.predict("Mojito recipe")

        assert isinstance(result, ClassificationResult)
        assert result.label == "recipe"
        assert result.confidence == 0.95
        assert "all_labels" in result.details

    def test_predict_returns_other_when_empty(
        self,
        sample_classes: Dict[str, str],
        _mock_provider: LLMConfig,
        mock_empty_label_response: str,
    ) -> None:
        """predict() returns 'other' with 0.0 confidence when no matches."""
        os.environ.setdefault("OPENAI_API_KEY", "dummy")
        mock_chat = Mock()
        mock_instance = Mock()
        mock_instance.invoke.return_value = AIMessage(
            content=mock_empty_label_response
        )
        mock_chat.return_value = mock_instance

        clf = _build_classifier(sample_classes, _mock_provider, mock_chat)
        result = clf.predict("Random text")

        assert result.label == "other"
        assert result.confidence == 0.0


# ============================================================================
# Utility Method Tests
# ============================================================================


class TestMultiLabelUtilities:
    """Test utility methods."""

    def test_fit_returns_self(
        self, sample_classes: Dict[str, str], _mock_provider: LLMConfig
    ) -> None:
        """fit() returns self (no-op)."""
        os.environ.setdefault("OPENAI_API_KEY", "dummy")
        clf = _build_classifier(sample_classes, _mock_provider, Mock())
        assert clf.fit([], []) is clf

    def test_get_classes(
        self, sample_classes: Dict[str, str], _mock_provider: LLMConfig
    ) -> None:
        """get_classes() returns copy of classes dict."""
        os.environ.setdefault("OPENAI_API_KEY", "dummy")
        clf = _build_classifier(sample_classes, _mock_provider, Mock())
        classes = clf.get_classes()

        assert classes == sample_classes
        classes["new"] = "should not affect original"
        assert "new" not in clf.classes

    def test_get_class_names(
        self, sample_classes: Dict[str, str], _mock_provider: LLMConfig
    ) -> None:
        """get_class_names() returns list of class names."""
        os.environ.setdefault("OPENAI_API_KEY", "dummy")
        clf = _build_classifier(sample_classes, _mock_provider, Mock())
        assert set(clf.get_class_names()) == set(sample_classes.keys())

    def test_get_llm_metadata(
        self, sample_classes: Dict[str, str], _mock_provider: LLMConfig
    ) -> None:
        """get_llm_metadata() returns provider config."""
        os.environ.setdefault("OPENAI_API_KEY", "dummy")
        clf = _build_classifier(sample_classes, _mock_provider, Mock())
        meta = clf.get_llm_metadata()

        assert meta["provider"] == "test_provider"
        assert meta["model"] == "test-model"
        assert "temperature" in meta


# ============================================================================
# Model Tests
# ============================================================================


class TestMultiLabelModels:
    """Test Pydantic models."""

    def test_label_score_creation(self) -> None:
        """LabelScore stores label and confidence."""
        ls = LabelScore(label="recipe", confidence=0.95)
        assert ls.label == "recipe"
        assert ls.confidence == 0.95

    def test_label_score_confidence_bounds(self) -> None:
        """LabelScore validates confidence bounds."""
        LabelScore(label="a", confidence=0.0)
        LabelScore(label="a", confidence=1.0)

        with pytest.raises(Exception):
            LabelScore(label="a", confidence=1.5)
        with pytest.raises(Exception):
            LabelScore(label="a", confidence=-0.1)

    def test_multilabel_result_creation(self) -> None:
        """MultiLabelClassificationResult creation."""
        result = MultiLabelClassificationResult(
            labels=[
                LabelScore(label="recipe", confidence=0.95),
                LabelScore(label="cocktail", confidence=0.88),
            ],
            reasoning="Contains mixing instructions",
            available_classes=["recipe", "cocktail", "restaurant"],
        )
        assert len(result.labels) == 2
        assert result.reasoning is not None
        assert len(result.available_classes) == 3

    def test_multilabel_result_empty(self) -> None:
        """MultiLabelClassificationResult with no labels."""
        result = MultiLabelClassificationResult(
            labels=[],
            reasoning="No match",
            available_classes=["a", "b"],
        )
        assert len(result.labels) == 0
