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


class MultiClassLLMClassifier(BaseClassifier):
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
        # Load configuration
        config = get_config(config_path)

        # Load classes from config
        config_classes = self._load_classes_from_config(config)

        # Merge config classes with runtime classes (runtime overrides config)
        self.classes = {**config_classes, **(classes or {})}

        # Validate classes
        if len(self.classes) < 2:
            raise ValueError(
                f"At least 2 classes are required for classification, got {len(self.classes)}. "
                f"Define classes in config.toml [classification.classes] or pass them to the constructor."
            )

        # Load LLM configuration from [llm] section
        llm_config = LLMConfig.from_config_manager(config)

        # Select provider: use specified or default from config
        selected_provider = provider_name or llm_config.default_provider

        # Validate provider exists and get configuration
        # Explicitly raises ValueError with informative message for API layer
        available_providers = [p.name for p in llm_config.providers]
        if selected_provider not in available_providers:
            raise ValueError(
                f"Provider '{selected_provider}' not found in configuration. "
                f"Available providers: {', '.join(available_providers)}"
            )

        # Get provider configuration (will not raise since we validated above)
        provider_cfg = get_provider_config(llm_config, selected_provider)
        self._provider_config = provider_cfg

        # Build llm_kwargs from provider configuration
        llm_kwargs = {
            "model": provider_cfg.model,
            "temperature": provider_cfg.temperature,
        }

        # Add optional parameters if present
        if provider_cfg.timeout:
            llm_kwargs["timeout"] = provider_cfg.timeout
        if provider_cfg.max_tokens:
            llm_kwargs["max_tokens"] = provider_cfg.max_tokens
        if provider_cfg.api_key:
            llm_kwargs["api_key"] = provider_cfg.api_key

        # Handle custom endpoints (LM Studio, Ollama)
        if provider_cfg.api_base:
            llm_kwargs["api_base"] = provider_cfg.api_base

            # For custom endpoints, set custom_llm_provider based on port/provider
            if '11434' in provider_cfg.api_base or provider_cfg.name.lower() == 'ollama':
                llm_kwargs["custom_llm_provider"] = "ollama"
            else:
                # LM Studio and other OpenAI-compatible endpoints
                llm_kwargs["custom_llm_provider"] = "openai"
        else:
            # Standard cloud providers - prefix model with provider name if needed
            if provider_cfg.name.lower() == 'ollama':
                llm_kwargs["model"] = f"ollama/{provider_cfg.model}"
            # OpenAI and Anthropic models don't need prefixing

        self.llm = ChatLiteLLM(**llm_kwargs)

        # Use PydanticOutputParser for structured output
        self.output_parser = PydanticOutputParser(pydantic_object=MultiClassResult)

        # Build prompt template
        self.prompt = self._build_prompt()

    def _load_classes_from_config(self, config) -> Dict[str, str]:
        """Load class definitions from config.toml.

        Args:
            config: ConfigManager instance.

        Returns:
            Dictionary mapping class names to descriptions.

        Example:
            Config format in config.toml:
            ```toml
            [[classification.classes]]
            name = "recipe"
            description = "Cooking instructions..."
            ```
        """
        classes = {}
        classification_section = config.get_section('classification')
        class_definitions = classification_section.get('classes', [])

        for class_def in class_definitions:
            name = class_def.get('name')
            description = class_def.get('description', '')
            if name:
                classes[name] = description

        return classes

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

    def get_classes(self) -> Dict[str, str]:
        """Get the current class definitions.

        Returns:
            Dictionary mapping class names to their descriptions.

        Example:
            ```python
            classifier = MultiClassLLMClassifier(classes={
                "recipe": "Cooking instructions",
                "news": "News articles"
            })
            print(classifier.get_classes())
            # {"recipe": "Cooking instructions", "news": "News articles"}
            ```
        """
        return self.classes.copy()

    def get_class_names(self) -> List[str]:
        """Get list of available class names.

        Returns:
            List of class names.

        Example:
            ```python
            classifier = MultiClassLLMClassifier(classes={...})
            print(classifier.get_class_names())
            # ["recipe", "python_package", "movie_review"]
            ```
        """
        return list(self.classes.keys())

    def get_llm_metadata(self) -> Dict[str, Any]:
        """Get LLM configuration metadata for storage/tracking.

        Returns:
            Dictionary with provider configuration (excluding sensitive api_key).

        Example:
            ```python
            classifier = MultiClassLLMClassifier(provider_name='openai')
            metadata = classifier.get_llm_metadata()
            print(metadata)
            # {
            #     'provider': 'openai',
            #     'model': 'gpt-4o-mini',
            #     'temperature': 0.7,
            #     'max_tokens': 1000
            # }
            ```
        """
        cfg = self._provider_config
        metadata: Dict[str, Any] = {
            "provider": cfg.name,
            "model": cfg.model,
            "temperature": cfg.temperature,
        }
        # Add optional fields if present
        if cfg.max_tokens:
            metadata["max_tokens"] = cfg.max_tokens
        if cfg.timeout:
            metadata["timeout"] = cfg.timeout
        if cfg.api_base:
            metadata["api_base"] = cfg.api_base
        return metadata

