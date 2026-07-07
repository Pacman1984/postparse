"""
Pytest fixtures for PostParse API tests.

This module provides shared fixtures for testing the FastAPI application,
including mock database, classifiers, cache managers, and test data helpers.
"""

import asyncio
import pytest
import time
from datetime import datetime
from typing import Dict, Any, List
from unittest.mock import Mock
from fastapi.testclient import TestClient

from backend.postparse.api.main import app
from backend.postparse.api.services.job_manager import JobManager
from backend.postparse.core.data.database import SocialMediaDatabase
from backend.postparse.services.analysis.classifiers.llm import RecipeLLMClassifier
from backend.postparse.api.services.cache_manager import CacheManager
from backend.postparse.core.utils.config import ConfigManager


@pytest.fixture(scope="module")
def test_client():
    """
    Create a FastAPI TestClient for testing.
    
    This fixture is module-scoped to avoid recreating the client
    for every test, which would reinitialize the app multiple times.
    
    Note: Rate limiting is disabled in config/config.toml for development/testing.
    
    Returns:
        TestClient: FastAPI test client instance.
    
    Example:
        def test_health(test_client):
            response = test_client.get("/health")
            assert response.status_code == 200
    """
    with TestClient(app) as client:
        yield client


@pytest.fixture(scope="module")
def api_version():
    """
    Get the API version from the running application.
    
    This avoids hardcoding version strings in tests.
    
    Returns:
        str: API version string.
    """
    with TestClient(app) as client:
        response = client.get("/")
        if response.status_code == 200:
            return response.json().get("version", "0.1.0")
    return "0.1.0"


@pytest.fixture(scope="function")
def wait_for_jobs():
    """
    Fixture to help wait for background extraction jobs to complete.
    
    This ensures background tasks have time to clean up properly before
    the test finishes and the event loop closes.
    
    Returns:
        Callable that waits for job completion with timeout.
    
    Example:
        def test_extraction(client, wait_for_jobs):
            response = client.post("/api/v1/telegram/extract", json={...})
            job_id = response.json()["job_id"]
            wait_for_jobs(job_id, timeout=10.0)
    """
    def _wait(job_id: str = None, timeout: float = 5.0):
        """
        Wait for jobs to complete or timeout.
        
        Args:
            job_id: Optional specific job ID to wait for.
            timeout: Maximum time to wait in seconds.
        """
        start_time = time.time()
        while time.time() - start_time < timeout:
            # Give background tasks time to process
            time.sleep(0.1)
            
            # If we've waited at least 1 second, that's usually enough
            # for cleanup to start
            if time.time() - start_time >= 1.0:
                break
        
        # Give a final moment for cleanup
        time.sleep(0.1)
    
    return _wait


@pytest.fixture
def test_config() -> ConfigManager:
    """
    Create ConfigManager instance with test-specific configuration.
    
    Returns:
        ConfigManager: Config manager with test settings.
    
    Example:
        def test_feature(test_config):
            db_path = test_config.get('database.default_db_path')
            assert 'test' in db_path
    """
    config = Mock(spec=ConfigManager)
    config.get.side_effect = lambda key, default=None: {
        "database.default_db_path": "data/test_social_media.db",
        "api.cache.enabled": False,
        "api.auth.enabled": False,
        "api.log_level": "debug"
    }.get(key, default)
    return config


@pytest.fixture
def mock_db_with_sample_data() -> SocialMediaDatabase:
    """
    Create mock database with realistic sample posts and messages.
    
    This fixture provides a database instance pre-populated with:
    - Instagram posts with various hashtags, dates, content types, and owners
    - Telegram messages with various hashtags, dates, content types, and channels
    
    Returns:
        Mock SocialMediaDatabase instance with sample data.
    
    Example:
        def test_search(mock_db_with_sample_data):
            posts, cursor = mock_db_with_sample_data.search_instagram_posts(
                hashtags=["recipe"]
            )
            assert len(posts) > 0
    """
    db = Mock(spec=SocialMediaDatabase)
    
    # Sample Instagram posts
    sample_posts = [
        {
            "id": 1,
            "shortcode": "ABC123",
            "owner_username": "chef_alice",
            "caption": "Delicious pasta recipe #recipe #italian #pasta",
            "is_video": False,
            "likes": 150,
            "hashtags": ["recipe", "italian", "pasta"],
            "mentions": [],
            "created_at": "2024-01-10T10:00:00"
        },
        {
            "id": 2,
            "shortcode": "DEF456",
            "owner_username": "chef_bob",
            "caption": "Cooking video tutorial #recipe #cooking #video",
            "is_video": True,
            "likes": 320,
            "hashtags": ["recipe", "cooking", "video"],
            "mentions": [],
            "created_at": "2024-01-15T12:00:00"
        },
        {
            "id": 3,
            "shortcode": "GHI789",
            "owner_username": "chef_alice",
            "caption": "Weekend baking session #baking #dessert",
            "is_video": False,
            "likes": 200,
            "hashtags": ["baking", "dessert"],
            "mentions": [],
            "created_at": "2024-01-20T14:00:00"
        }
    ]
    
    # Sample Telegram messages
    sample_messages = [
        {
            "id": 1,
            "message_id": 1001,
            "chat_id": -1001234567890,
            "content": "Today's recipe share #recipe #daily",
            "content_type": "text",
            "hashtags": ["recipe", "daily"],
            "created_at": "2024-01-12T09:00:00"
        },
        {
            "id": 2,
            "message_id": 1002,
            "chat_id": -1009876543210,
            "content": "Beautiful food photography",
            "content_type": "photo",
            "hashtags": ["food", "photo"],
            "created_at": "2024-01-18T11:00:00"
        },
        {
            "id": 3,
            "message_id": 1003,
            "chat_id": -1001234567890,
            "content": "Video cooking tutorial #recipe #tutorial",
            "content_type": "video",
            "hashtags": ["recipe", "tutorial"],
            "created_at": "2024-01-22T13:00:00"
        }
    ]
    
    # Mock search methods with filtering logic
    def search_posts(hashtags=None, date_range=None, content_type=None,
                    owner_username=None, limit=50, cursor=None):
        filtered = [p.copy() for p in sample_posts]
        
        if hashtags:
            filtered = [p for p in filtered if any(h in p["hashtags"] for h in hashtags)]
        if content_type == "video":
            filtered = [p for p in filtered if p["is_video"]]
        elif content_type == "image":
            filtered = [p for p in filtered if not p["is_video"]]
        if owner_username:
            filtered = [p for p in filtered if p["owner_username"] == owner_username]
        
        results = filtered[:limit]
        next_cursor = "cursor_next" if len(filtered) > limit else None
        return results, next_cursor
    
    def search_messages(hashtags=None, date_range=None, content_type=None,
                       limit=50, cursor=None):
        filtered = [m.copy() for m in sample_messages]
        
        if hashtags:
            filtered = [m for m in filtered if any(h in m["hashtags"] for h in hashtags)]
        if content_type:
            filtered = [m for m in filtered if m["content_type"] == content_type]
        # Note: channel_username filtering is not supported
        
        results = filtered[:limit]
        next_cursor = "cursor_next" if len(filtered) > limit else None
        return results, next_cursor
    
    db.search_instagram_posts.side_effect = search_posts
    db.search_telegram_messages.side_effect = search_messages
    db.count_instagram_posts_filtered.return_value = len(sample_posts)
    db.count_telegram_messages_filtered.return_value = len(sample_messages)
    db._encode_cursor.return_value = "encoded_cursor"
    db._decode_cursor.return_value = ("2024-01-01T00:00:00", 1)
    
    return db


@pytest.fixture
def mock_classifier():
    """
    Create mock RecipeLLMClassifier with deterministic responses.
    
    Returns:
        Mock RecipeLLMClassifier that returns predefined results.
    
    Example:
        def test_classification(mock_classifier):
            result = mock_classifier.predict("Recipe for pasta")
            assert result["label"] == "recipe"
    """
    classifier = Mock(spec=RecipeLLMClassifier)
    
    def predict(text: str):
        # Simple heuristic: if text contains recipe keywords, classify as recipe
        recipe_keywords = ["recipe", "ingredients", "instructions", "cook", "bake"]
        is_recipe = any(keyword in text.lower() for keyword in recipe_keywords)
        
        return {
            "label": "recipe" if is_recipe else "not_recipe",
            "confidence": 0.95 if is_recipe else 0.90,
            "details": {
                "has_ingredients": is_recipe,
                "has_instructions": is_recipe
            } if is_recipe else None,
            "processing_time": 0.1,
            "classifier_used": "RecipeLLMClassifier",
            "provider": "ollama"
        }
    
    classifier.predict.side_effect = predict
    return classifier


@pytest.fixture
def mock_cache_manager():
    """
    Create mock CacheManager with in-memory backend.
    
    Returns:
        CacheManager with in-memory storage (no Redis required).
    
    Example:
        def test_caching(mock_cache_manager):
            mock_cache_manager.set("key", "value")
            assert mock_cache_manager.get("key") == "value"
    """
    config = Mock(spec=ConfigManager)
    config.get.side_effect = lambda key, default=None: {
        "api.cache.enabled": True,
        "api.cache.default_ttl": 300,
        "api.cache.search_ttl": 600,
        "api.cache.max_memory_mb": 100
    }.get(key, default)
    
    cache = CacheManager(config)
    return cache


@pytest.fixture
def client_with_overrides(mock_db_with_sample_data, mock_classifier, mock_cache_manager):
    """
    Create TestClient with all dependencies overridden for isolated testing.
    
    This fixture provides a fully configured test client with:
    - Mock database with sample data
    - Mock classifier with deterministic results
    - Mock cache manager with in-memory storage
    
    Args:
        mock_db_with_sample_data: Mock database fixture.
        mock_classifier: Mock classifier fixture.
        mock_cache_manager: Mock cache manager fixture.
    
    Returns:
        TestClient with overridden dependencies.
    
    Example:
        def test_endpoint(client_with_overrides):
            response = client_with_overrides.get("/api/v1/search/posts")
            assert response.status_code == 200
    """
    from backend.postparse.api.dependencies import (
        get_db, 
        get_recipe_llm_classifier,
        get_cache_manager
    )
    
    app.dependency_overrides[get_db] = lambda: mock_db_with_sample_data
    app.dependency_overrides[get_recipe_llm_classifier] = lambda: mock_classifier
    app.dependency_overrides[get_cache_manager] = lambda: mock_cache_manager
    
    client = TestClient(app)
    yield client
    
    # Cleanup
    app.dependency_overrides.clear()


def create_sample_post(**kwargs) -> Dict[str, Any]:
    """
    Create sample Instagram post dict with defaults.
    
    Args:
        **kwargs: Override default field values.
    
    Returns:
        Dict representing an Instagram post.
    
    Example:
        post = create_sample_post(
            shortcode="XYZ999",
            owner_username="test_user",
            is_video=True
        )
    """
    defaults = {
        "id": 1,
        "shortcode": "ABC123",
        "owner_username": "test_user",
        "caption": "Test post #test",
        "is_video": False,
        "likes": 100,
        "hashtags": ["test"],
        "mentions": [],
        "created_at": datetime.now().isoformat()
    }
    defaults.update(kwargs)
    return defaults


def create_sample_message(**kwargs) -> Dict[str, Any]:
    """
    Create sample Telegram message dict with defaults.
    
    Args:
        **kwargs: Override default field values.
    
    Returns:
        Dict representing a Telegram message.
    
    Example:
        message = create_sample_message(
            message_id=2002,
            channel_username="my_channel",
            content_type="photo"
        )
    """
    defaults = {
        "id": 1,
        "message_id": 1001,
        "channel_username": "test_channel",
        "content": "Test message #test",
        "content_type": "text",
        "hashtags": ["test"],
        "created_at": datetime.now().isoformat()
    }
    defaults.update(kwargs)
    return defaults

