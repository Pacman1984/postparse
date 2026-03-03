"""Multi-label LLM classifier for assigning multiple categories per item.

This module provides a multi-label classifier that can assign **multiple**
categories to a single text, each with an individual confidence score.

The classifier uses:
- **LangChain**: For PydanticOutputParser, prompts, and structured outputs
- **LiteLLM**: As universal adapter supporting ANY LLM provider

Key difference from MultiClassLLMClassifier:
- MultiClass: picks exactly ONE best category per text
- MultiLabel: assigns ALL matching categories (0 to N) per text

Configuration:
    Classes can be defined in config.toml [classification.classes] section
    and/or passed at runtime via the constructor.

Example:
    ```python
    from postparse.services.analysis.classifiers import MultiLabelLLMClassifier

    classifier = MultiLabelLLMClassifier()
    result = classifier.predict_multilabel(
        "Try this mojito recipe at the beach bar!"
    )
    for label in result.labels:
        print(f"{label.label}: {label.confidence:.0%}")
    # cocktail: 95%
    # recipe: 88%
    # bar_cafe: 72%
    ```
"""

from typing import Any, Dict, List, Optional

from langchain_core.prompts import PromptTemplate
from langchain_core.output_parsers import PydanticOutputParser
from langchain_litellm import ChatLiteLLM
from pydantic import BaseModel, Field

from .base import (
    BaseClassifier,
    ClassificationResult,
    LabelScore,
    MultiLabelClassificationResult,
)
from backend.postparse.core.utils.config import get_config
from backend.postparse.llm.config import LLMConfig, get_provider_config


class MultiLabelLLMResult(BaseModel):
    """Structured LLM output for multi-label classification.

    This is the Pydantic model the LLM is instructed to return via
    PydanticOutputParser. It is mapped to ``MultiLabelClassificationResult``
    after validation.

    Attributes:
        predicted_classes: List of dicts with 'label' and 'confidence' keys.
        reasoning: Brief explanation for the assigned labels.

    Example:
        ```python
        result = MultiLabelLLMResult(
            predicted_classes=[
                {"label": "recipe", "confidence": 0.95},
                {"label": "cocktail", "confidence": 0.88},
            ],
            reasoning="Contains cocktail mixing instructions with ingredients",
        )
        ```
    """

    predicted_classes: List[Dict[str, Any]] = Field(
        ...,
        description=(
            "List of ALL matching categories. Each entry must have "
            "'label' (str) and 'confidence' (float 0.0-1.0). "
            "Return an empty list if no category matches."
        ),
    )
    reasoning: Optional[str] = Field(
        None, description="Brief explanation for the assigned labels"
    )


class MultiLabelLLMClassifier(BaseClassifier):
    """LLM-based multi-label classifier that assigns multiple categories per item.

    Unlike ``MultiClassLLMClassifier`` which picks exactly one category,
    this classifier assigns **all** matching categories with individual
    confidence scores.

    Features:
        - **Multi-Label**: Assigns 0..N labels per text
        - **Dynamic Classes**: Define any number of classes (minimum 2)
        - **Config + Runtime**: Load classes from config and override at runtime
        - **Provider Flexibility**: Any LiteLLM-supported provider
        - **Structured Output**: Returns list of labels with confidence + reasoning

    Attributes:
        classes: Dictionary mapping class names to their descriptions.
        llm: ChatLiteLLM instance for inference.
        output_parser: PydanticOutputParser for structured output.
        prompt: PromptTemplate for classification requests.

    Example:
        ```python
        classifier = MultiLabelLLMClassifier()

        # Multi-label prediction
        result = classifier.predict_multilabel("Mojito recipe at beach bar")
        for lbl in result.labels:
            print(f"{lbl.label}: {lbl.confidence:.0%}")

        # Single-label fallback (highest confidence)
        single = classifier.predict("Mojito recipe at beach bar")
        print(single.label)  # "cocktail"
        ```
    """

    def __init__(
        self,
        classes: Optional[Dict[str, str]] = None,
        provider_name: Optional[str] = None,
        config_path: Optional[str] = None,
    ):
        """Initialize the multi-label LLM classifier.

        Args:
            classes: Runtime class definitions (dict mapping class name to
                description). If None, loads from config. Runtime classes
                override config classes for duplicate keys.
            provider_name: Name of the provider from [llm.providers] in
                config.toml. If None, uses default_provider from config.
            config_path: Path to configuration file. If None, uses default.

        Raises:
            ValueError: If fewer than 2 classes are defined.
            ValueError: If provider_name is not found in configuration.

        Example:
            ```python
            classifier = MultiLabelLLMClassifier()
            classifier = MultiLabelLLMClassifier(
                classes={"a": "Desc A", "b": "Desc B"},
                provider_name="openai",
            )
            ```
        """
        config = get_config(config_path)

        config_classes = self._load_classes_from_config(config)
        self.classes: Dict[str, str] = {**config_classes, **(classes or {})}

        if len(self.classes) < 2:
            raise ValueError(
                f"At least 2 classes required, got {len(self.classes)}. "
                "Define in config.toml [classification.classes] or pass them."
            )

        llm_config = LLMConfig.from_config_manager(config)
        selected_provider = provider_name or llm_config.default_provider

        available_providers = [p.name for p in llm_config.providers]
        if selected_provider not in available_providers:
            raise ValueError(
                f"Provider '{selected_provider}' not found. "
                f"Available: {', '.join(available_providers)}"
            )

        provider_cfg = get_provider_config(llm_config, selected_provider)
        self._provider_config = provider_cfg

        llm_kwargs: Dict[str, Any] = {
            "model": provider_cfg.model,
            "temperature": provider_cfg.temperature,
        }
        if provider_cfg.timeout:
            llm_kwargs["timeout"] = provider_cfg.timeout
        if provider_cfg.max_tokens:
            llm_kwargs["max_tokens"] = provider_cfg.max_tokens
        if provider_cfg.api_key:
            llm_kwargs["api_key"] = provider_cfg.api_key

        if provider_cfg.api_base:
            llm_kwargs["api_base"] = provider_cfg.api_base
            if (
                "11434" in provider_cfg.api_base
                or provider_cfg.name.lower() == "ollama"
            ):
                llm_kwargs["custom_llm_provider"] = "ollama"
            else:
                llm_kwargs["custom_llm_provider"] = "openai"
        else:
            if provider_cfg.name.lower() == "ollama":
                llm_kwargs["model"] = f"ollama/{provider_cfg.model}"

        self.llm = ChatLiteLLM(**llm_kwargs)
        self.output_parser = PydanticOutputParser(
            pydantic_object=MultiLabelLLMResult
        )
        self.prompt = self._build_prompt()

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _load_classes_from_config(self, config: Any) -> Dict[str, str]:
        """Load class definitions from config.toml [classification.classes].

        Args:
            config: ConfigManager instance.

        Returns:
            Dictionary mapping class names to descriptions.
        """
        classes: Dict[str, str] = {}
        classification_section = config.get_section("classification")
        for class_def in classification_section.get("classes", []):
            name = class_def.get("name")
            description = class_def.get("description", "")
            if name:
                classes[name] = description
        return classes

    def _build_prompt(self) -> PromptTemplate:
        """Build the multi-label classification prompt template.

        Returns:
            PromptTemplate configured with class definitions and format
            instructions for multi-label output.
        """
        class_definitions = "\n".join(
            f"- **{name}**: {desc}"
            for name, desc in self.classes.items()
        )
        available_classes = ", ".join(
            f'"{name}"' for name in self.classes.keys()
        )

        prompt_template = f"""You are a multi-label text classification assistant. \
Assign ALL categories that apply to the given text.

## Available Categories:

{class_definitions}

## Instructions:

1. Read the input text carefully
2. Identify EVERY category that applies to the content
3. A text can match 0, 1, or multiple categories
4. For each matching category, assign a confidence score (0.0-1.0)
5. Only assign categories where confidence >= 0.6
6. Provide brief reasoning explaining your label assignments

## Important:
- You may ONLY use these categories: {available_classes}
- Do NOT invent new categories
- Assign ALL that genuinely apply, not just the best one
- If nothing matches well, return an empty list
- Order results by confidence (highest first)

## Input Text:

{{content}}

{{format_instructions}}
"""

        return PromptTemplate(
            template=prompt_template,
            input_variables=["content"],
            partial_variables={
                "format_instructions": (
                    self.output_parser.get_format_instructions()
                )
            },
        )

    def _validate_label(self, label: str) -> Optional[str]:
        """Validate and normalize a predicted label against available classes.

        Args:
            label: The label string returned by the LLM.

        Returns:
            The normalized label name, or None if invalid.
        """
        if label in self.classes:
            return label
        for class_name in self.classes:
            if class_name.lower() == label.lower():
                return class_name
        return None

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    def fit(self, X: Any, y: Optional[Any] = None) -> "MultiLabelLLMClassifier":
        """No-op: LLM classifiers don't require training.

        Args:
            X: Training data (ignored).
            y: Target values (ignored).

        Returns:
            self
        """
        return self

    def predict_multilabel(self, X: str) -> MultiLabelClassificationResult:
        """Classify text and return ALL matching labels.

        This is the primary method for multi-label classification.

        Args:
            X: Text content to classify.

        Returns:
            MultiLabelClassificationResult with list of LabelScore entries.

        Example:
            ```python
            result = classifier.predict_multilabel(
                "Best pasta recipe from that Italian restaurant"
            )
            for lbl in result.labels:
                print(f"{lbl.label}: {lbl.confidence:.0%}")
            # recipe: 92%
            # restaurant: 85%
            ```
        """
        formatted_prompt = self.prompt.format(content=X)
        response = self.llm.invoke(formatted_prompt)
        parsed: MultiLabelLLMResult = self.output_parser.parse(
            response.content
        )

        valid_labels: List[LabelScore] = []
        for entry in parsed.predicted_classes:
            raw_label = entry.get("label", "")
            confidence = float(entry.get("confidence", 0.0))
            normalized = self._validate_label(raw_label)
            if normalized is not None:
                valid_labels.append(
                    LabelScore(
                        label=normalized,
                        confidence=min(max(confidence, 0.0), 1.0),
                    )
                )

        valid_labels.sort(key=lambda ls: ls.confidence, reverse=True)

        return MultiLabelClassificationResult(
            labels=valid_labels,
            reasoning=parsed.reasoning,
            available_classes=list(self.classes.keys()),
        )

    def predict(self, X: str) -> ClassificationResult:
        """Classify text and return the single highest-confidence label.

        Backward-compatible wrapper around ``predict_multilabel`` that
        satisfies the ``BaseClassifier`` interface.

        Args:
            X: Text content to classify.

        Returns:
            ClassificationResult with the top label.

        Example:
            ```python
            result = classifier.predict("Mojito recipe at beach bar")
            print(result.label)       # "cocktail"
            print(result.confidence)  # 0.95
            ```
        """
        ml_result = self.predict_multilabel(X)

        if ml_result.labels:
            top = ml_result.labels[0]
            return ClassificationResult(
                label=top.label,
                confidence=top.confidence,
                details={
                    "reasoning": ml_result.reasoning,
                    "all_labels": [
                        {"label": ls.label, "confidence": ls.confidence}
                        for ls in ml_result.labels
                    ],
                    "available_classes": ml_result.available_classes,
                },
            )

        return ClassificationResult(
            label="other",
            confidence=0.0,
            details={
                "reasoning": ml_result.reasoning or "No category matched.",
                "all_labels": [],
                "available_classes": ml_result.available_classes,
            },
        )

    def get_classes(self) -> Dict[str, str]:
        """Get the current class definitions.

        Returns:
            Dictionary mapping class names to descriptions.
        """
        return self.classes.copy()

    def get_class_names(self) -> List[str]:
        """Get list of available class names.

        Returns:
            List of class name strings.
        """
        return list(self.classes.keys())

    def get_llm_metadata(self) -> Dict[str, Any]:
        """Get LLM configuration metadata for storage/tracking.

        Returns:
            Dictionary with provider configuration (excluding api_key).
        """
        cfg = self._provider_config
        metadata: Dict[str, Any] = {
            "provider": cfg.name,
            "model": cfg.model,
            "temperature": cfg.temperature,
        }
        if cfg.max_tokens:
            metadata["max_tokens"] = cfg.max_tokens
        if cfg.timeout:
            metadata["timeout"] = cfg.timeout
        if cfg.api_base:
            metadata["api_base"] = cfg.api_base
        return metadata
