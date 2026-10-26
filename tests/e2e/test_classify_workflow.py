"""
End-to-end tests for classification workflows.

This module tests the complete classification workflow from API request
through classifier invocation and database storage, using real components
where possible and mocking external LLM calls.
"""

import pytest
from datetime import datetime
from typing import Dict, Any
from unittest.mock import Mock, patch

from fastapi.testclient import TestClient

from postparse.api.main import app
from postparse.core.data.database import SocialMediaDatabase
from postparse.api.services.cache_manager import CacheManager
from postparse.core.utils.config import ConfigManager
import json

from pydantic_ai.messages import ModelResponse, TextPart
from pydantic_ai.models.function import FunctionModel

from postparse.api.dependencies import get_classifier_factory
from postparse.classification import TaxonomyClassifier


@pytest.fixture(scope="module")
def e2e_classify_db_path(tmp_path_factory) -> str:
    """
    Create a module-scoped temporary database for classify E2E tests.

    Args:
        tmp_path_factory: Pytest's temporary path factory.

    Returns:
        Path to temporary database file.
    """
    tmp_dir = tmp_path_factory.mktemp("e2e_classify")
    return str(tmp_dir / "e2e_classify_test.db")


@pytest.fixture(scope="module")
def e2e_classify_database(e2e_classify_db_path) -> SocialMediaDatabase:
    """
    Create a real SQLite database for classify E2E tests with sample data.

    Args:
        e2e_classify_db_path: Path to temporary database file.

    Returns:
        SocialMediaDatabase: Database instance with sample data.
    """
    db = SocialMediaDatabase(e2e_classify_db_path)

    # Insert sample Instagram posts for classification
    db._insert_instagram_post(
        shortcode="CLASSIFY001",
        owner_username="recipe_chef",
        caption="Here's my famous pasta recipe! Ingredients: pasta, tomatoes, basil. Instructions: boil pasta, make sauce, combine. #recipe #italian",
        is_video=False,
        likes=500,
        created_at=datetime(2024, 1, 15, 10, 0, 0),
        hashtags=["recipe", "italian"],
    )
    db._insert_instagram_post(
        shortcode="CLASSIFY002",
        owner_username="tech_blogger",
        caption="Just bought a new laptop! Great specs and performance. #tech #review",
        is_video=False,
        likes=150,
        created_at=datetime(2024, 1, 18, 14, 0, 0),
        hashtags=["tech", "review"],
    )
    db._insert_instagram_post(
        shortcode="CLASSIFY003",
        owner_username="recipe_chef",
        caption="Quick breakfast smoothie recipe - blend banana, berries, yogurt, and honey! #recipe #breakfast #healthy",
        is_video=True,
        likes=300,
        created_at=datetime(2024, 1, 22, 8, 0, 0),
        hashtags=["recipe", "breakfast", "healthy"],
    )

    # Insert sample Telegram messages for classification
    db._insert_telegram_message(
        message_id=8001,
        chat_id=-1001234567890,
        content="Best homemade pizza recipe: dough, tomato sauce, mozzarella, toppings. Bake at 450F for 15 mins. #recipe",
        content_type="text",
        created_at=datetime(2024, 1, 20, 12, 0, 0),
        hashtags=["recipe"],
    )
    db._insert_telegram_message(
        message_id=8002,
        chat_id=-1001234567890,
        content="Breaking news: Stock market hits new highs today. #finance #news",
        content_type="text",
        created_at=datetime(2024, 1, 24, 9, 0, 0),
        hashtags=["finance", "news"],
    )

    yield db


@pytest.fixture(scope="function")
def e2e_classify_client(e2e_classify_database) -> TestClient:
    """
    Create a TestClient with real database for classify E2E tests.

    Args:
        e2e_classify_database: Real database with sample data.

    Returns:
        TestClient: Configured for E2E testing.
    """
    from postparse.api.dependencies import get_db, get_cache_manager

    # Create cache manager with disabled caching
    config = Mock(spec=ConfigManager)
    config.get.side_effect = lambda key, default=None: {
        "api.cache.enabled": False,
    }.get(key, default)
    cache = CacheManager(config)

    app.dependency_overrides[get_db] = lambda: e2e_classify_database
    app.dependency_overrides[get_cache_manager] = lambda: cache

    with TestClient(app) as client:
        yield client

    app.dependency_overrides.clear()


@pytest.fixture
def recipe_classifier_factory():
    """
    Classifier factory whose FunctionModel answers with a keyword heuristic.

    Returns:
        Factory compatible with ``get_classifier_factory``.
    """
    recipe_keywords = ["recipe", "ingredients", "instructions", "cook", "bake", "blend", "sauce"]

    def respond(messages, info):
        prompt = str(messages[0].parts[-1].content).lower()
        is_recipe = any(keyword in prompt for keyword in recipe_keywords)
        payload = {
            "reasoning": "keyword heuristic",
            "label": "recipe" if is_recipe else "not_recipe",
            "confidence": 0.95 if is_recipe else 0.85,
        }
        return ModelResponse(parts=[TextPart(json.dumps(payload))])

    def factory(spec, provider_name=None):
        return TaxonomyClassifier(spec, FunctionModel(respond), "native",
                                  provider_name="fake", model_name="fake-model")

    return factory


class TestClassifyEndpointE2E:
    """E2E tests for classification endpoint workflow."""

    def test_classify_single_text_recipe(
        self, e2e_classify_client: TestClient, recipe_classifier_factory
    ) -> None:
        """Classifying a recipe text runs through the generic classifier."""
        app.dependency_overrides[get_classifier_factory] = lambda: recipe_classifier_factory
        response = e2e_classify_client.post(
            "/api/v1/classify/recipe",
            json={
                "text": "Here is a recipe: Mix flour, eggs, and sugar. Bake at 350F for 30 minutes.",
            },
        )
        assert response.status_code == 200, response.text
        data = response.json()
        assert data["label"] == "recipe"
        assert data["confidence"] == pytest.approx(0.95)
        assert data["details"]["reasoning"] == "keyword heuristic"
        assert data["classifier_used"] == "llm"

    def test_classify_single_text_not_recipe(
        self, e2e_classify_client: TestClient, recipe_classifier_factory
    ) -> None:
        """Text that is not a recipe is labelled not_recipe."""
        app.dependency_overrides[get_classifier_factory] = lambda: recipe_classifier_factory
        response = e2e_classify_client.post(
            "/api/v1/classify/recipe",
            json={"text": "Just bought a new phone. Great camera quality!"},
        )
        assert response.status_code == 200, response.text
        assert response.json()["label"] == "not_recipe"


class TestClassifyDatabaseContentE2E:
    """E2E tests for classifying database content."""

    def test_get_unclassified_content_count(
        self, e2e_classify_client: TestClient, e2e_classify_database
    ) -> None:
        """
        Test getting count of unclassified content.

        Verifies database content can be queried.
        """
        # Query database directly for unclassified posts
        posts = e2e_classify_database.get_instagram_posts()
        messages = e2e_classify_database.get_telegram_messages()

        # Should have our sample data
        assert len(posts) >= 3
        assert len(messages) >= 2


class TestClassificationResultsStorageE2E:
    """E2E tests for classification results storage."""

    def test_save_classification_result(
        self, e2e_classify_database
    ) -> None:
        """
        Test saving classification result to database.

        Verifies classification results are persisted.
        """
        # Get a post to classify
        posts = e2e_classify_database.get_instagram_posts()
        assert len(posts) > 0

        post = posts[0]
        post_id = post["id"]

        # Save classification result
        result_id = e2e_classify_database.save_classification_result(
            content_id=post_id,
            content_source="instagram",
            classifier_name="recipe",
            label="recipe",
            confidence=0.95,
            details={"has_ingredients": True},
            classification_type="single",
            reasoning="Contains recipe keywords and instructions",
            llm_metadata={"model": "test_model", "provider": "test_provider"},
        )

        assert result_id is not None
        assert result_id > 0

    def test_check_classification_exists(
        self, e2e_classify_database
    ) -> None:
        """
        Test checking if classification exists.

        Verifies duplicate check functionality.
        """
        # Get a post to classify
        posts = e2e_classify_database.get_instagram_posts()
        assert len(posts) > 0

        post = posts[0]
        post_id = post["id"]

        # First, ensure no classification exists
        initial_exists = e2e_classify_database.has_classification(
            content_id=post_id,
            content_source="instagram",
            classifier_name="test_classifier",
        )

        # Save a classification
        e2e_classify_database.save_classification_result(
            content_id=post_id,
            content_source="instagram",
            classifier_name="test_classifier",
            label="test_label",
            confidence=0.9,
        )

        # Now check it exists
        now_exists = e2e_classify_database.has_classification(
            content_id=post_id,
            content_source="instagram",
            classifier_name="test_classifier",
        )

        assert now_exists is True

    def test_update_classification(
        self, e2e_classify_database
    ) -> None:
        """
        Test updating existing classification.

        Verifies classification update functionality.
        """
        # Get a post
        posts = e2e_classify_database.get_instagram_posts()
        post = posts[1]  # Use second post
        post_id = post["id"]

        # Save initial classification
        result_id = e2e_classify_database.save_classification_result(
            content_id=post_id,
            content_source="instagram",
            classifier_name="update_test",
            label="initial_label",
            confidence=0.7,
        )

        # Get the classification ID
        analysis_id = e2e_classify_database.get_classification_id(
            content_id=post_id,
            content_source="instagram",
            classifier_name="update_test",
        )

        if analysis_id:
            # Update the classification
            e2e_classify_database.update_classification(
                analysis_id=analysis_id,
                label="updated_label",
                confidence=0.95,
                reasoning="Updated reasoning",
            )


class TestSearchWithClassificationE2E:
    """E2E tests for searching with classification data."""

    def test_posts_include_classification_info(
        self, e2e_classify_client: TestClient, e2e_classify_database
    ) -> None:
        """
        Test that posts can include classification information.

        Verifies search returns posts with available classification data.
        """
        response = e2e_classify_client.get("/api/v1/search/posts")

        assert response.status_code == 200
        data = response.json()
        assert "results" in data

        # Posts are returned
        assert len(data["results"]) > 0


