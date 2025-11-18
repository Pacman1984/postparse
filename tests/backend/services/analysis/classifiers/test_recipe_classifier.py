"""Test the recipe classifier with Instagram captions."""
import pytest
from postparse.core.data.database import SocialMediaDatabase

# Check if skollama is available
try:
    from postparse.services.analysis.classifiers.recipe_classifier import RecipeClassifier, SKOLLAMA_AVAILABLE
except ImportError:
    SKOLLAMA_AVAILABLE = False
    RecipeClassifier = None

# Check if LangChain/LiteLLM is available
try:
    from postparse.services.analysis.classifiers.llm import RecipeLLMClassifier
    LANGCHAIN_AVAILABLE = True
except ImportError:
    LANGCHAIN_AVAILABLE = False
    RecipeLLMClassifier = None

@pytest.mark.skipif(not SKOLLAMA_AVAILABLE, reason="skollama package not installed")
def test_recipe_classification():
    """Test recipe classification on Instagram captions."""
    # Initialize classifier and database
    classifier = RecipeClassifier()
    db = SocialMediaDatabase()
    
    # Test with a sample recipe text
    recipe_text = """Here's my favorite pasta recipe! 
    Ingredients:
    - 500g pasta
    - 2 cloves garlic
    - Olive oil
    Instructions:
    1. Boil pasta
    2. Sauté garlic
    3. Mix and enjoy!"""
    
    result = classifier.predict(recipe_text)
    print(f"\nSample recipe text classification: {result}")
    
    # Test with non-recipe text
    non_recipe = "Beautiful sunset at the beach today! The waves were amazing."
    result = classifier.predict(non_recipe)
    print(f"\nSample non-recipe text classification: {result}")
    
    # Test with real Instagram posts if available
    # Note: This requires posts to be in the database
    with db as conn:
        cursor = conn._cursor
        cursor.execute("SELECT caption FROM instagram_posts WHERE caption IS NOT NULL LIMIT 5")
        posts = cursor.fetchall()
        
        for post in posts:
            caption = post[0]
            result = classifier.predict(caption)
            print(f"\nCaption: {caption[:100]}...")
            print(f"Classification: {result}")

@pytest.mark.skipif(not LANGCHAIN_AVAILABLE, reason="langchain/litellm packages not installed")
def test_llm_recipe_classification():
    """Test LiteLLM-based recipe classification.
    
    Note: This test requires either:
    1. Ollama running with qwen3:14b model loaded, OR
    2. LM Studio running on http://localhost:1234
    
    To run with Ollama:
        ollama pull qwen3:14b
        ollama serve
    
    To run with LM Studio:
        Set OPENAI_API_KEY="dummy" in environment
    """
    import os
    
    # Set dummy API key for custom endpoints (LM Studio, Ollama)
    os.environ.setdefault("OPENAI_API_KEY", "dummy-key-for-local")
    
    try:
        classifier = RecipeLLMClassifier()
        
        # Test with recipe text
        recipe_text = """Here's my favorite pasta recipe! 
        Ingredients:
        - 500g pasta
        - 2 cloves garlic
        - Olive oil
        Instructions:
        1. Boil pasta
        2. Sauté garlic
        3. Mix and enjoy!"""
        
        result = classifier.predict(recipe_text)
        print(f"\nLLM Recipe text classification: {result}")
        assert result.label == "recipe"
        assert result.confidence > 0
        assert result.details is not None
        print(f"Recipe details: {result.details}")
        
        # Test with non-recipe text
        non_recipe = "Beautiful sunset at the beach today! The waves were amazing."
        result = classifier.predict(non_recipe)
        print(f"\nLLM Non-recipe text classification: {result}")
        assert result.label == "not_recipe"
        assert result.confidence > 0
        
    except Exception as e:
        # Skip if model not available
        if "not found" in str(e) or "connection" in str(e).lower():
            pytest.skip(f"LLM model not available: {e}")
        else:
            raise