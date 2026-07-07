"""Multi-class LLM classifier for dynamic category classification.

This module provides a flexible multi-class classifier that can classify text into
arbitrary categories defined via configuration or runtime parameters.

The classifier uses:
- **LangChain**: For PydanticOutputParser, prompts, and structured outputs
- **LiteLLM**: As universal adapter supporting ANY LLM provider

Configuration:
    Classes can be defined in config.toml [classification.classes] section
    and/or passed at runtime via the constructor.

Example:
    Using classes from config:
    
    ```python
    from postparse.services.analysis.classifiers import MultiClassLLMClassifier
    
    classifier = MultiClassLLMClassifier()
    result = classifier.predict("Check out this new FastAPI library!")
    print(result.label)  # "python_package"
    print(result.confidence)  # 0.92
    print(result.details['reasoning'])  # "The text mentions FastAPI library..."
    ```
    
    Using runtime classes:
    
    ```python
    classes = {
        "recipe": "Cooking instructions or ingredients",
        "tech_news": "Technology news or product announcements",
        "sports": "Sports news, scores, or athlete updates"
    }
    
    classifier = MultiClassLLMClassifier(classes=classes, provider_name='openai')
    result = classifier.predict("Apple announces new iPhone 16")
    print(result.label)  # "tech_news"
    ```
"""

from typing import Any, Dict, List, Optional

from langchain_core.prompts import PromptTemplate
from langchain_core.output_parsers import PydanticOutputParser
from langchain_litellm import ChatLiteLLM
from pydantic import BaseModel, Field

from .base import BaseClassifier, ClassificationResult
from ._shared import LLMClassifierCommon
from backend.postparse.core.utils.config import get_config
from backend.postparse.llm.config import LLMConfig, get_provider_config


class MultiClassResult(BaseModel):
    """Structured output for multi-class classification.

    Attributes:
        predicted_class: The predicted class name.
        confidence: Confidence score between 0.0 and 1.0.
        reasoning: Explanation for the classification decision.

    Example:
        ```python
        result = MultiClassResult(
            predicted_class="python_package",
            confidence=0.92,
            reasoning="The text mentions FastAPI library and APIs"
        )
        ```
    """

    predicted_class: str = Field(..., description="The predicted class name from available classes")
    confidence: float = Field(..., ge=0.0, le=1.0, description="Confidence score (0.0-1.0)")
    reasoning: Optional[str] = Field(None, description="Explanation for the classification")


class MultiClassLLMClassifier(LLMClassifierCommon, BaseClassifier):
    """LLM-based multi-class classifier with dynamic category definitions.

    This classifier extends BaseClassifier to provide flexible multi-class
    classification using LangChain + LiteLLM. Categories can be defined via
    config.toml or passed at runtime.

    Features:
        - **Dynamic Classes**: Define any number of classes (minimum 2)
        - **Config + Runtime**: Load classes from config and override at runtime
        - **Provider Flexibility**: Use any LLM provider (OpenAI, Anthropic, Ollama, etc.)
        - **Structured Output**: Returns predicted class, confidence, and reasoning

    Attributes:
        classes: Dictionary mapping class names to their descriptions.
        llm: ChatLiteLLM instance for inference.
        output_parser: PydanticOutputParser for structured output.
        prompt: PromptTemplate for classification requests.

    Example:
        Using classes from config:

        ```python
        classifier = MultiClassLLMClassifier()
        result = classifier.predict("Check out this new FastAPI library!")
        print(result.label)  # "python_package"
        ```

        Using runtime classes:

        ```python
        classes = {
            "recipe": "Cooking instructions or ingredients",
            "python_package": "Python libraries or packages",
            "movie_review": "Movie or film discussion"
        }
        classifier = MultiClassLLMClassifier(classes=classes, provider_name='openai')
        result = classifier.predict("Great movie last night!")
        print(result.label)  # "movie_review"
        ```

        Batch classification:

        ```python
        texts = ["Boil pasta for 10 minutes", "New Python 3.13 released"]
        results = classifier.predict_batch(texts)
        for text, result in zip(texts, results):
            print(f"{text[:30]}... -> {result.label}")
        ```
    """

    def __init__(
        self,
        classes: Optional[Dict[str, str]] = None,
        provider_name: Optional[str] = None,
        config_path: Optional[str] = None
    ):
        """Initialize the multi-class LLM classifier.

        Args:
            classes: Runtime class definitions (dict mapping class name to description).
                If None, loads from config. Runtime classes override config classes
                for duplicate keys.
            provider_name: Name of the provider to use from [llm.providers] in config.toml.
                If None, uses the default_provider from config.
                Examples: 'openai', 'ollama', 'lm_studio', 'anthropic'
            config_path: Path to configuration file. If None, uses default locations.

        Raises:
            ValueError: If no classes are defined or less than 2 classes.
            ValueError: If provider_name is not found in configuration.

        Example:
            ```python
            # Use default provider and classes from config
            classifier = MultiClassLLMClassifier()

            # Use specific provider with runtime classes
            classifier = MultiClassLLMClassifier(
                classes={"cat1": "Description 1", "cat2": "Description 2"},
                provider_name='openai'
            )
            ```
        """
        # Load configuration and initialize shared components
        config = get_config(config_path)
        self._initialize_classes(classes, config)
        # Provide patchable references for tests
        self._LLMConfig = LLMConfig
        self._ChatLiteLLM = ChatLiteLLM
        self.llm = self._initialize_llm(provider_name, config)

        # Use PydanticOutputParser for structured output
        self.output_parser = PydanticOutputParser(pydantic_object=MultiClassResult)

        # Build prompt template
        self.prompt = self._build_prompt()

    def _build_prompt(self) -> PromptTemplate:
        """Build the classification prompt template.

        Returns:
            PromptTemplate configured with class definitions and format instructions.
        """
        # Build class definitions section
        class_definitions = "\n".join(
            f"- **{name}**: {description}"
            for name, description in self.classes.items()
        )

        available_classes = ", ".join(f'"{name}"' for name in self.classes.keys())

        prompt_template = f"""You are a text classification assistant. Classify the given text into one of the following categories.

## Available Categories:

{class_definitions}

## Instructions:

1. Read the input text carefully
2. Determine which category best fits the content
3. Assign a confidence score (0.0-1.0) based on how certain you are
4. Provide brief reasoning for your classification

## Important:
- You MUST choose one of these categories: {available_classes}
- Do not invent new categories
- If the text doesn't clearly fit any category, choose the closest match and reflect uncertainty in the confidence score

## Input Text:

{{content}}

{{format_instructions}}
"""

        return PromptTemplate(
            template=prompt_template,
            input_variables=["content"],
            partial_variables={
                "format_instructions": self.output_parser.get_format_instructions()
            }
        )

    def fit(self, X: Any, y: Optional[Any] = None) -> 'MultiClassLLMClassifier':
        """LLM classifiers don't require training.

        This method exists to satisfy the BaseClassifier interface.

        Args:
            X: Training data (ignored).
            y: Target values (ignored).

        Returns:
            self: The classifier instance.

        Example:
            ```python
            classifier = MultiClassLLMClassifier(classes={...})
            classifier.fit(None)  # No-op
            ```
        """
        return self

    def predict(self, X: str) -> ClassificationResult:
        """Classify input text into one of the defined categories.

        Args:
            X: Text content to classify.

        Returns:
            ClassificationResult with label, confidence, and details including
            reasoning and available classes.

        Raises:
            ValueError: If the LLM returns a class not in the available classes.

        Example:
            ```python
            classifier = MultiClassLLMClassifier(classes={
                "recipe": "Cooking instructions",
                "tech_news": "Technology news"
            })
            result = classifier.predict("Apple announces new iPhone")
            print(result.label)  # "tech_news"
            print(result.confidence)  # 0.89
            print(result.details['reasoning'])  # "The text discusses..."
            ```
        """
        # Format prompt with content
        formatted_prompt = self.prompt.format(content=X)

        # Get LLM response
        response = self.llm.invoke(formatted_prompt)

        # Parse response to MultiClassResult
        parsed_result = self.output_parser.parse(response.content)

        # Validate predicted class
        if parsed_result.predicted_class not in self.classes:
            # Try case-insensitive match
            matched_class = None
            for class_name in self.classes.keys():
                if class_name.lower() == parsed_result.predicted_class.lower():
                    matched_class = class_name
                    break

            if matched_class:
                parsed_result.predicted_class = matched_class
            else:
                raise ValueError(
                    f"LLM returned invalid class '{parsed_result.predicted_class}'. "
                    f"Valid classes are: {list(self.classes.keys())}"
                )

        return ClassificationResult(
            label=parsed_result.predicted_class,
            confidence=parsed_result.confidence,
            details={
                'reasoning': parsed_result.reasoning,
                'available_classes': list(self.classes.keys())
            }
        )
 

