"""
Pytest configuration for unit tests.

Unit tests should be isolated, fast, and mock all external dependencies.
"""

import pytest
from unittest.mock import Mock, MagicMock


@pytest.fixture
def mock_config():
    """
    Create a mock ConfigManager for unit tests.

    Returns:
        Mock ConfigManager instance with common test defaults.

    Example:
        def test_something(mock_config):
            mock_config.get.return_value = "custom_value"
            # use mock_config...
    """
    config = Mock()
    config.get.return_value = None
    config.get_section.return_value = {}
    config.config_path = "config/config.toml"
    return config


@pytest.fixture
def mock_db():
    """
    Create a minimal mock database for unit tests.

    Returns:
        Mock SocialMediaDatabase instance.

    Example:
        def test_something(mock_db):
            mock_db.search_instagram_posts.return_value = ([], None)
            # test code...
    """
    db = Mock()
    db.search_instagram_posts.return_value = ([], None)
    db.search_telegram_messages.return_value = ([], None)
    db.count_instagram_posts_filtered.return_value = 0
    db.count_telegram_messages_filtered.return_value = 0
    db.has_classification.return_value = False
    return db


