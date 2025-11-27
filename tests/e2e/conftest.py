"""
Pytest configuration for end-to-end tests.

E2E tests test complete workflows from API entry points through
to database operations and back. They use real components where possible.
"""

import pytest
import tempfile
from pathlib import Path
from unittest.mock import Mock

from fastapi.testclient import TestClient

from backend.postparse.api.main import app
from backend.postparse.core.data.database import SocialMediaDatabase
from backend.postparse.api.services.cache_manager import CacheManager
from backend.postparse.core.utils.config import ConfigManager


@pytest.fixture(scope="session")
def e2e_db_path(tmp_path_factory):
    """
    Create a session-scoped temporary database for E2E tests.

    Args:
        tmp_path_factory: Pytest's temporary path factory.

    Returns:
        Path to temporary database file.
    """
    tmp_dir = tmp_path_factory.mktemp("e2e")
    return str(tmp_dir / "e2e_test.db")


@pytest.fixture(scope="session")
def e2e_database(e2e_db_path):
    """
    Create a real SQLite database for E2E tests with sample data.

    Args:
        e2e_db_path: Path to temporary database file.

    Returns:
        SocialMediaDatabase: Database instance with sample data.
    """
    db = SocialMediaDatabase(e2e_db_path)

    # Insert sample data for E2E tests
    from datetime import datetime

    # Sample Instagram posts
    db._insert_instagram_post(
        shortcode="E2E001",
        owner_username="e2e_chef",
        caption="Delicious pasta recipe #recipe #italian",
        is_video=False,
        likes=100,
        created_at=datetime(2024, 1, 15, 10, 0, 0),
        hashtags=["recipe", "italian"],
    )
    db._insert_instagram_post(
        shortcode="E2E002",
        owner_username="e2e_baker",
        caption="Baking tutorial video #recipe #baking #video",
        is_video=True,
        likes=250,
        created_at=datetime(2024, 1, 20, 14, 0, 0),
        hashtags=["recipe", "baking", "video"],
    )
    db._insert_instagram_post(
        shortcode="E2E003",
        owner_username="e2e_travel",
        caption="Beautiful sunset at the beach #travel #nature",
        is_video=False,
        likes=500,
        created_at=datetime(2024, 1, 25, 18, 0, 0),
        hashtags=["travel", "nature"],
    )

    # Sample Telegram messages
    db._insert_telegram_message(
        message_id=9001,
        chat_id=-1001234567890,
        content="Today's recipe: homemade pizza #recipe #daily",
        content_type="text",
        created_at=datetime(2024, 1, 18, 9, 0, 0),
        hashtags=["recipe", "daily"],
    )
    db._insert_telegram_message(
        message_id=9002,
        chat_id=-1001234567890,
        content="Tech news update #tech #news",
        content_type="text",
        created_at=datetime(2024, 1, 22, 12, 0, 0),
        hashtags=["tech", "news"],
    )

    yield db


@pytest.fixture(scope="function")
def e2e_client(e2e_database):
    """
    Create a TestClient with real database for E2E tests.

    Args:
        e2e_database: Real database with sample data.

    Returns:
        TestClient: Configured for E2E testing.
    """
    from backend.postparse.api.dependencies import get_db, get_cache_manager

    # Create cache manager with in-memory storage
    config = Mock(spec=ConfigManager)
    config.get.side_effect = lambda key, default=None: {
        "api.cache.enabled": False,  # Disable caching for E2E tests
    }.get(key, default)
    cache = CacheManager(config)

    app.dependency_overrides[get_db] = lambda: e2e_database
    app.dependency_overrides[get_cache_manager] = lambda: cache

    with TestClient(app) as client:
        yield client

    app.dependency_overrides.clear()


