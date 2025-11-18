"""Classification models for recipe detection and analysis.

This module provides classifiers for detecting and analyzing recipe content
from social media posts and messages using LangChain + LiteLLM.

The classifier uses:
- **LangChain**: For PydanticOutputParser, prompts, and structured outputs
- **LiteLLM**: As universal adapter supporting ANY LLM provider (Ollama, LM Studio, OpenAI, Anthropic, etc.)

Example:
    Recipe classification with structured output:
    
    ```python
    from postparse.services.analysis.classifiers import RecipeLLMClassifier
    
    classifier = RecipeLLMClassifier()
    result = classifier.predict("Here's my pasta recipe: ...")
    
    # Structured output
    print(result.label)                    # "recipe" or "not_recipe"
    print(result.confidence)               # 0.0-1.0
    print(result.details['cuisine_type']) # "Italian"
    print(result.details['difficulty'])   # "easy", "medium", "hard"
    print(result.details['meal_type'])    # "breakfast", "lunch", "dinner", "dessert"
    ```
    
    The classifier automatically works with any LiteLLM-supported provider
    configured in config.toml (Ollama, LM Studio, OpenAI, etc.).
"""

from postparse.services.analysis.classifiers.base import BaseClassifier, ClassificationResult
from postparse.services.analysis.classifiers.llm import RecipeLLMClassifier, RecipeDetails

__all__ = [
    "BaseClassifier",
    "ClassificationResult",
    "RecipeLLMClassifier",
    "RecipeDetails",
]

