"""
Pytest configuration for unit tests.

Unit tests should be isolated, fast, and mock all external dependencies.
"""

import pytest
from unittest.mock import Mock


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
