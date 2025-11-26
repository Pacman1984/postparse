"""Classification models for recipe detection and multi-class analysis.

This module provides classifiers for detecting and analyzing content
from social media posts and messages using LangChain + LiteLLM.

The classifiers use:
- **LangChain**: For PydanticOutputParser, prompts, and structured outputs
- **LiteLLM**: As universal adapter supporting ANY LLM provider (Ollama, LM Studio, OpenAI, Anthropic, etc.)

Configuration:
    Uses [llm] config section; old [models] section is deprecated.

Architecture:
    ChatLiteLLM via LiteLLM provides unified interface for all providers.

Available Classifiers:
    - **RecipeLLMClassifier**: Binary recipe classification (recipe / not_recipe)
    - **MultiClassLLMClassifier**: Dynamic multi-class classification with custom categories

Example:
    Recipe classification with structured output:

    ```python
    from postparse.services.analysis.classifiers import RecipeLLMClassifier

    # Use default provider from config
    classifier = RecipeLLMClassifier()

    # Or specify provider from [llm.providers]
    classifier = RecipeLLMClassifier(provider_name='openai')

    result = classifier.predict("Here's my pasta recipe: ...")

    # Structured output
    print(result.label)                    # "recipe" or "not_recipe"
    print(result.confidence)               # 0.0-1.0
    print(result.details['cuisine_type']) # "Italian"
    print(result.details['difficulty'])   # "easy", "medium", "hard"
    print(result.details['meal_type'])    # "breakfast", "lunch", "dinner", "dessert"
    ```

    Multi-class classification with dynamic classes:

    ```python
    from postparse.services.analysis.classifiers import MultiClassLLMClassifier

    # Define classes at runtime
    classes = {
        "recipe": "A text containing cooking instructions, ingredients, or recipe details",
        "python_package": "A text about Python packages, libraries, or pip installations",
        "movie_review": "A text reviewing or discussing movies, films, or cinema"
    }

    classifier = MultiClassLLMClassifier(classes=classes)
    result = classifier.predict("Check out this new FastAPI library!")
    print(result.label)  # "python_package"
    print(result.confidence)  # 0.92
    print(result.details['reasoning'])  # "The text mentions FastAPI library..."
    ```

    The classifiers automatically work with any LiteLLM-supported provider
    configured in config.toml (Ollama, LM Studio, OpenAI, etc.).
"""

from backend.postparse.services.analysis.classifiers.base import BaseClassifier, ClassificationResult
from backend.postparse.services.analysis.classifiers.llm import RecipeLLMClassifier, RecipeDetails
from backend.postparse.services.analysis.classifiers.multi_class import (
    MultiClassLLMClassifier,
    MultiClassResult,
)

__all__ = [
    "BaseClassifier",
    "ClassificationResult",
    "RecipeLLMClassifier",
    "RecipeDetails",
    "MultiClassLLMClassifier",
    "MultiClassResult",
]

