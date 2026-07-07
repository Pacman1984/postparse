"""Pytest configuration and fixtures for classifier tests.

This module provides shared fixtures for testing recipe classifiers,
including mock LLM providers and sample test data.
"""

import pytest
from unittest.mock import Mock
from langchain_core.messages import AIMessage
from langchain_community.chat_models import ChatLiteLLM
from backend.postparse.llm import LLMProvider
from backend.postparse.llm.config import LLMConfig, ProviderConfig


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


@pytest.fixture
def mock_recipe_json_response():
    """Mock LLM JSON response for recipe classification.
    
    Returns:
        str: JSON string representing RecipeDetails with is_recipe=True
        
    Example:
        ```python
        def test_classifier(mock_recipe_json_response):
            # Use in mocked llm.invoke().content
            mock_llm.invoke.return_value = AIMessage(content=mock_recipe_json_response)
        ```
    """
    return '{"is_recipe": true, "cuisine_type": "Italian", "difficulty": "easy", "meal_type": "dinner", "ingredients_count": 5}'


@pytest.fixture
def mock_non_recipe_json_response():
    """Mock LLM JSON response for non-recipe classification.
    
    Returns:
        str: JSON string representing RecipeDetails with is_recipe=False
    """
    return '{"is_recipe": false, "cuisine_type": null, "difficulty": null, "meal_type": null, "ingredients_count": null}'


@pytest.fixture
def mock_chat_litellm(mock_recipe_json_response):
    """Mock ChatLiteLLM instance with recipe response.
    
    Args:
        mock_recipe_json_response: Fixture providing JSON response
        
    Returns:
        Mock: Configured ChatLiteLLM mock with invoke method
        
    Example:
        ```python
        def test_with_mock(mock_chat_litellm):
            # Mock is already configured with invoke returning recipe JSON
            result = mock_chat_litellm.invoke("test prompt")
            assert "is_recipe" in result.content
        ```
    """
    llm = Mock(spec=ChatLiteLLM)
    llm.invoke.return_value = AIMessage(content=mock_recipe_json_response)
    return llm


@pytest.fixture
def mock_llm_config():
    """Mock LLMConfig with test providers.
    
    Returns:
        LLMConfig: Configured with lm_studio, ollama, and openai providers
        
    Example:
        ```python
        def test_config(mock_llm_config):
            assert mock_llm_config.default_provider == 'lm_studio'
            provider = mock_llm_config.get_provider('openai')
            assert provider.model == 'gpt-4o-mini'
        ```
    """
    return LLMConfig(
        default_provider='lm_studio',
        enable_fallback=True,
        providers=[
            ProviderConfig(
                name='lm_studio',
                model='qwen/qwen3-vl-8b',
                api_base='http://localhost:1234/v1',
                timeout=60
            ),
            ProviderConfig(
                name='ollama',
                model='qwen3:14b',
                api_base='http://localhost:11434',
                timeout=30
            ),
            ProviderConfig(
                name='openai',
                model='gpt-4o-mini',
                timeout=30
            )
        ]
    )


@pytest.fixture
def mock_provider_config_openai():
    """Mock ProviderConfig for OpenAI.
    
    Returns:
        ProviderConfig: OpenAI configuration for testing
    """
    return ProviderConfig(
        name='openai',
        model='gpt-4o-mini',
        temperature=0.7,
        timeout=30,
        max_tokens=1000
    )

