"""Pytest configuration and fixtures for classifier tests.

This module provides shared fixtures for testing recipe classifiers,
including mock LLM providers and sample test data.
"""

import pytest
from unittest.mock import Mock
from postparse.llm import LLMProvider


@pytest.fixture
def mock_llm_provider():
    """Create a mock LLM provider for testing.
    
    This fixture provides a configured mock that implements the LLMProvider
    interface. Tests can configure the return values as needed.
    
    Returns:
        Mock: A mock LLMProvider instance with common methods configured
        
    Example:
        ```python
        def test_classifier(mock_llm_provider):
            mock_llm_provider.chat.return_value = "YES"
            classifier = RecipeClassifier(provider=mock_llm_provider)
            result = classifier.predict("test")
            assert result == "recipe"
        ```
    """
    provider = Mock(spec=LLMProvider)
    provider.get_provider_name.return_value = "mock_provider"
    provider.get_model_name.return_value = "mock_model"
    provider.chat.return_value = "YES"
    return provider


@pytest.fixture
def sample_recipe_text():
    """Sample recipe text for testing.
    
    Returns:
        str: A realistic recipe text with ingredients and instructions
    """
    return """Here's my favorite pasta recipe! 
    Ingredients:
    - 500g pasta
    - 2 cloves garlic
    - Olive oil
    - Salt and pepper to taste
    
    Instructions:
    1. Boil pasta in salted water for 10 minutes
    2. While pasta cooks, sauté minced garlic in olive oil
    3. Drain pasta and toss with garlic oil
    4. Season with salt and pepper
    5. Serve hot and enjoy!"""


@pytest.fixture
def sample_non_recipe_text():
    """Sample non-recipe text for testing.
    
    Returns:
        str: A non-recipe text sample for negative classification tests
    """
    return "Beautiful sunset at the beach today! The waves were amazing and the sky was painted in shades of orange and pink."


@pytest.fixture
def mock_llm_response_recipe():
    """Mock LLM response indicating recipe content.
    
    Returns:
        str: A response string that should be classified as recipe
    """
    return "YES"


@pytest.fixture
def mock_llm_response_non_recipe():
    """Mock LLM response indicating non-recipe content.
    
    Returns:
        str: A response string that should be classified as not recipe
    """
    return "NO"

