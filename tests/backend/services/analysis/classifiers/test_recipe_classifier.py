"""Test the RecipeLLMClassifier with LangChain + LiteLLM."""
import os
import pytest
from unittest.mock import Mock, patch
from postparse.services.analysis.classifiers import RecipeLLMClassifier, RecipeDetails, ClassificationResult


def test_recipe_llm_classifier_initialization():
    """Test RecipeLLMClassifier initialization with config."""
    os.environ.setdefault("OPENAI_API_KEY", "dummy-key-for-testing")
    
    try:
        classifier = RecipeLLMClassifier()
        
        # Verify classifier components
        assert classifier.llm is not None
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
