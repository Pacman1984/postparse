"""Test the recipe classifier with Instagram captions."""
import pytest
from postparse.core.data.database import SocialMediaDatabase

# Check if skollama is available
try:
    from postparse.services.analysis.classifiers.recipe_classifier import RecipeClassifier, SKOLLAMA_AVAILABLE
except ImportError:
    SKOLLAMA_AVAILABLE = False
    RecipeClassifier = None

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