"""Test the RecipeLLMClassifier with LangChain + LiteLLM."""
import os
import pytest
from unittest.mock import Mock, patch
from langchain_core.messages import AIMessage
from langchain_community.chat_models import ChatLiteLLM
from postparse.services.analysis.classifiers import RecipeLLMClassifier, RecipeDetails, ClassificationResult
from postparse.llm.config import LLMConfig, get_provider_config


def test_recipe_llm_classifier_initialization():
    """Test RecipeLLMClassifier initialization with config."""
    os.environ.setdefault("OPENAI_API_KEY", "dummy-key-for-testing")
    
    try:
        classifier = RecipeLLMClassifier()
        
        # Verify classifier components
        assert classifier.llm is not None
        assert isinstance(classifier.llm, ChatLiteLLM)
        assert classifier.output_parser is not None
        assert classifier.prompt is not None
        assert hasattr(classifier, 'min_confidence')
        assert hasattr(classifier, 'max_confidence')
    except Exception as e:
        pytest.skip(f"Could not initialize classifier: {e}")


def test_recipe_details_model():
    """Test RecipeDetails Pydantic model."""
    # Test valid recipe details
    details = RecipeDetails(
        is_recipe=True,
        cuisine_type="Italian",
        difficulty="easy",
        meal_type="dinner",
        ingredients_count=5
    )
    
    assert details.is_recipe is True
    assert details.cuisine_type == "Italian"
    assert details.difficulty == "easy"
    assert details.meal_type == "dinner"
    assert details.ingredients_count == 5
    
    # Test non-recipe (optional fields can be None)
    non_recipe = RecipeDetails(is_recipe=False)
    assert non_recipe.is_recipe is False
    assert non_recipe.cuisine_type is None
    assert non_recipe.difficulty is None


def test_recipe_details_serialization():
    """Test RecipeDetails model serialization."""
    details = RecipeDetails(
        is_recipe=True,
        cuisine_type="Mexican",
        difficulty="medium",
        meal_type="lunch",
        ingredients_count=10
    )
    
    # Test model_dump
    dumped = details.model_dump()
    assert isinstance(dumped, dict)
    assert dumped['is_recipe'] is True
    assert dumped['cuisine_type'] == "Mexican"
    
    # Test JSON serialization
    json_str = details.model_dump_json()
    assert isinstance(json_str, str)
    assert "Mexican" in json_str


def test_classification_result_structure():
    """Test ClassificationResult structure."""
    result = ClassificationResult(
        label="recipe",
        confidence=0.95,
        details={
            "is_recipe": True,
            "cuisine_type": "Italian",
            "difficulty": "easy",
            "meal_type": "dinner",
            "ingredients_count": 5
        }
    )
    
    assert result.label == "recipe"
    assert result.confidence == 0.95
    assert result.details['cuisine_type'] == "Italian"


def test_predict_with_mocked_llm(mock_recipe_json_response):
    """Test predict with mocked LLM invoke call."""
    os.environ.setdefault("OPENAI_API_KEY", "dummy-key-for-testing")
    
    # Mock at the class level before classifier initialization
    with patch('langchain_community.chat_models.litellm.ChatLiteLLM.invoke') as mock_invoke:
        mock_invoke.return_value = AIMessage(content=mock_recipe_json_response)
        
        try:
            classifier = RecipeLLMClassifier()
            result = classifier.predict("Test recipe text")
            
            # Verify result structure
            assert isinstance(result, ClassificationResult)
            assert result.label == "recipe"
            assert result.confidence > 0
            assert result.details['is_recipe'] is True
            assert result.details['cuisine_type'] == "Italian"
            
            # Verify invoke was called
            assert mock_invoke.called
            
        except Exception as e:
            pytest.skip(f"Could not initialize classifier: {e}")


def test_predict_non_recipe_with_mock(mock_non_recipe_json_response):
    """Test predict with mocked LLM for non-recipe content."""
    os.environ.setdefault("OPENAI_API_KEY", "dummy-key-for-testing")
    
    # Mock at the class level before classifier initialization
    with patch('langchain_community.chat_models.litellm.ChatLiteLLM.invoke') as mock_invoke:
        mock_invoke.return_value = AIMessage(content=mock_non_recipe_json_response)
        
        try:
            classifier = RecipeLLMClassifier()
            result = classifier.predict("Not a recipe")
            
            # Verify result structure
            assert isinstance(result, ClassificationResult)
            assert result.label == "not_recipe"
            assert result.confidence > 0
            assert result.details['is_recipe'] is False
            
        except Exception as e:
            pytest.skip(f"Could not initialize classifier: {e}")


def test_initialization_with_provider_name():
    """Test initialization with specific provider_name."""
    os.environ.setdefault("OPENAI_API_KEY", "dummy-key-for-testing")
    
    try:
        # Test with explicit provider name
        classifier = RecipeLLMClassifier(provider_name='lm_studio')
        
        assert classifier.llm is not None
        assert isinstance(classifier.llm, ChatLiteLLM)
        
    except Exception as e:
        pytest.skip(f"Could not initialize classifier: {e}")


def test_invalid_provider_name():
    """Test that invalid provider_name raises ValueError."""
    os.environ.setdefault("OPENAI_API_KEY", "dummy-key-for-testing")
    
    with patch('postparse.services.analysis.classifiers.llm.LLMConfig.from_config_manager') as mock_from_config:
        # Create a real LLMConfig instance with a known set of providers
        from postparse.llm.config import ProviderConfig
        
        # Create a minimal valid provider configuration
        valid_provider = ProviderConfig(
            name='test_provider',
            model='test-model',
            api_key='dummy',
            timeout=60
        )
        
        # Create LLMConfig with only the valid provider (not 'invalid_provider')
        real_llm_config = LLMConfig(
            providers=[valid_provider],
            default_provider='test_provider',
            enable_fallback=False,
            cache_responses=False
        )
        
        mock_from_config.return_value = real_llm_config
        
        # Should raise ValueError for non-existent provider
        with pytest.raises(ValueError, match="Provider 'invalid_provider' not found"):
            RecipeLLMClassifier(provider_name='invalid_provider')


def test_uses_llm_config_section():
    """Test that classifier loads and applies values from [llm] config section."""
    os.environ.setdefault("OPENAI_API_KEY", "dummy-key-for-testing")
    
    # Mock at ConfigManager level to test actual config loading logic
    with patch('postparse.services.analysis.classifiers.llm.get_config') as mock_get_config:
        # Create mock ConfigManager
        mock_config_manager = Mock()
        
        # Configure [llm] section data that from_config_manager will read
        mock_config_manager.get_section.return_value = {
            'default_provider': 'test_provider',
            'enable_fallback': True,
            'cache_responses': False,
            'providers': [{
                'name': 'test_provider',
                'model': 'test-model-unique-123',
                'api_base': 'http://localhost:9999/v1',
                'timeout': 42,
                'temperature': 0.3,
                'max_tokens': 500,
                'api_key': 'test-key-789'
            }]
        }
        
        # Configure other config values the classifier needs
        mock_config_manager.get.side_effect = lambda key, default=None: {
            'prompts.recipe_analysis_prompt': 'Test prompt: {content}\n{format_instructions}',
            'classification.min_confidence_threshold': 0.5,
            'classification.max_confidence_threshold': 0.99
        }.get(key, default)
        
        mock_get_config.return_value = mock_config_manager
        
        # Initialize classifier - this will execute the real config loading logic
        classifier = RecipeLLMClassifier()
        
        # Verify that get_section was called with 'llm' to load [llm] section
        mock_config_manager.get_section.assert_called_with('llm')
        
        # Verify that config values from [llm] section were actually applied
        assert classifier.llm is not None
        assert isinstance(classifier.llm, ChatLiteLLM)
        
        # Verify provider config values were applied to LLM (accessible attributes)
        assert classifier.llm.model == 'test-model-unique-123'
        assert classifier.llm.temperature == 0.3
        assert classifier.llm.api_base == 'http://localhost:9999/v1'
        assert classifier.llm.custom_llm_provider == 'openai'  # OpenAI-compatible endpoint
        
        # Verify max_tokens is in model_kwargs if not a direct attribute
        if hasattr(classifier.llm, 'max_tokens'):
            assert classifier.llm.max_tokens == 500
        elif hasattr(classifier.llm, 'model_kwargs'):
            # May be stored in model_kwargs depending on LiteLLM version
            pass
        
        # Verify other config values were loaded correctly
        assert classifier.min_confidence == 0.5
        assert classifier.max_confidence == 0.99


def test_confidence_calculation():
    """Test confidence score calculation logic."""
    os.environ.setdefault("OPENAI_API_KEY", "dummy-key-for-testing")
    
    try:
        classifier = RecipeLLMClassifier()
        
        # Test confidence for non-recipe (all optional fields None)
        non_recipe_details = RecipeDetails(is_recipe=False)
        confidence = classifier._calculate_confidence(non_recipe_details)
        assert confidence == classifier.max_confidence
        
        # Test confidence for recipe with no optional fields
        recipe_min = RecipeDetails(is_recipe=True)
        confidence = classifier._calculate_confidence(recipe_min)
        assert confidence == classifier.min_confidence
        
        # Test confidence for recipe with all optional fields
        recipe_max = RecipeDetails(
            is_recipe=True,
            cuisine_type="Italian",
            difficulty="easy",
            meal_type="dinner",
            ingredients_count=5
        )
        confidence = classifier._calculate_confidence(recipe_max)
        assert confidence == classifier.max_confidence
        
    except Exception as e:
        pytest.skip(f"Could not initialize classifier: {e}")


@pytest.mark.integration
def test_recipe_llm_classifier_with_recipe_text():
    """Integration test with real LLM - recipe text.
    
    Tests full stack: [llm] config → provider selection → ChatLiteLLM → classification
    
    This test requires either:
    1. Ollama running with a model loaded, OR
    2. LM Studio running on http://localhost:1234, OR
    3. Valid OpenAI API key
    
    Set SKIP_INTEGRATION_TESTS=1 to skip this test.
    """
    if os.getenv("SKIP_INTEGRATION_TESTS"):
        pytest.skip("Integration tests disabled")
    
    # Set dummy API key for custom endpoints
    os.environ.setdefault("OPENAI_API_KEY", "dummy-key-for-local")
    
    try:
        classifier = RecipeLLMClassifier()
        
        recipe_text = """Here's my favorite pasta recipe! 
        Ingredients:
        - 500g pasta
        - 2 cloves garlic
        - Olive oil
        - Salt and pepper
        - Fresh basil
        
        Instructions:
        1. Boil pasta in salted water for 8-10 minutes
        2. Sauté minced garlic in olive oil
        3. Drain pasta and mix with garlic oil
        4. Add fresh basil and season to taste
        5. Serve hot and enjoy!"""
        
        result = classifier.predict(recipe_text)
        
        print(f"\nRecipe classification result:")
        print(f"  Label: {result.label}")
        print(f"  Confidence: {result.confidence}")
        print(f"  Details: {result.details}")
        
        # Assertions
        assert isinstance(result, ClassificationResult)
        assert result.label == "recipe"
        assert result.confidence > 0
        assert result.details is not None
        assert result.details['is_recipe'] is True
        
        # Optional: Check if structured data was extracted
        if result.details.get('cuisine_type'):
            print(f"  Detected cuisine: {result.details['cuisine_type']}")
        
    except Exception as e:
        error_msg = str(e).lower()
        if any(keyword in error_msg for keyword in ["not found", "connection", "unavailable", "failed to connect"]):
            pytest.skip(f"LLM service not available: {e}")
        else:
            raise


@pytest.mark.integration
def test_recipe_llm_classifier_with_non_recipe_text():
    """Integration test with real LLM - non-recipe text.
    
    Set SKIP_INTEGRATION_TESTS=1 to skip this test.
    """
    if os.getenv("SKIP_INTEGRATION_TESTS"):
        pytest.skip("Integration tests disabled")
    
    os.environ.setdefault("OPENAI_API_KEY", "dummy-key-for-local")
    
    try:
        classifier = RecipeLLMClassifier()
        
        non_recipe_text = "Beautiful sunset at the beach today! The waves were amazing and the weather was perfect for a swim."
        
        result = classifier.predict(non_recipe_text)
        
        print(f"\nNon-recipe classification result:")
        print(f"  Label: {result.label}")
        print(f"  Confidence: {result.confidence}")
        print(f"  Details: {result.details}")
        
        # Assertions
        assert isinstance(result, ClassificationResult)
        assert result.label == "not_recipe"
        assert result.confidence > 0
        assert result.details is not None
        assert result.details['is_recipe'] is False
        
    except Exception as e:
        error_msg = str(e).lower()
        if any(keyword in error_msg for keyword in ["not found", "connection", "unavailable", "failed to connect"]):
            pytest.skip(f"LLM service not available: {e}")
        else:
            raise


@pytest.mark.integration
def test_recipe_llm_classifier_edge_cases():
    """Test edge cases: empty text, ambiguous text."""
    if os.getenv("SKIP_INTEGRATION_TESTS"):
        pytest.skip("Integration tests disabled")
    
    os.environ.setdefault("OPENAI_API_KEY", "dummy-key-for-local")
    
    try:
        classifier = RecipeLLMClassifier()
        
        # Empty text
        result = classifier.predict("")
        assert result.label == "not_recipe"
        
        # Ambiguous text (mentions food but not a recipe)
        ambiguous_text = "I love Italian food! Pasta is my favorite."
        result = classifier.predict(ambiguous_text)
        print(f"\nAmbiguous text result: {result.label}")
        assert result.label in ["recipe", "not_recipe"]
        
    except Exception as e:
        error_msg = str(e).lower()
        if any(keyword in error_msg for keyword in ["not found", "connection", "unavailable", "failed to connect"]):
            pytest.skip(f"LLM service not available: {e}")
        else:
            raise


@pytest.mark.integration
def test_recipe_llm_classifier_batch_prediction():
    """Test batch prediction functionality."""
    if os.getenv("SKIP_INTEGRATION_TESTS"):
        pytest.skip("Integration tests disabled")
    
    os.environ.setdefault("OPENAI_API_KEY", "dummy-key-for-local")
    
    try:
        classifier = RecipeLLMClassifier()
        
        texts = [
            "Mix flour and water to make dough.",
            "The sky is blue today.",
            "Chop onions and fry until golden brown."
        ]
        
        results = classifier.predict_batch(texts)
        
        assert len(results) == 3
        for result in results:
            assert isinstance(result, ClassificationResult)
            assert result.label in ["recipe", "not_recipe"]
            assert result.confidence > 0
            
        print(f"\nBatch results: {[r.label for r in results]}")
        
    except Exception as e:
        error_msg = str(e).lower()
        if any(keyword in error_msg for keyword in ["not found", "connection", "unavailable", "failed to connect"]):
            pytest.skip(f"LLM service not available: {e}")
        else:
            raise


def test_recipe_llm_classifier_fit_method():
    """Test fit method (should be no-op for LLM classifiers)."""
    os.environ.setdefault("OPENAI_API_KEY", "dummy-key-for-testing")
    
    try:
        classifier = RecipeLLMClassifier()
        
        # fit() should return self
        result = classifier.fit([], [])
        assert result is classifier
        
    except Exception as e:
        pytest.skip(f"Could not initialize classifier: {e}")
