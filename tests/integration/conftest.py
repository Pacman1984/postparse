"""
Pytest configuration for integration tests.

Integration tests test the interaction between multiple components
and may use real databases (in-memory SQLite) and services.
"""

import pytest
import warnings

from postparse.core.data.database import SocialMediaDatabase


@pytest.fixture(scope="function")
def temp_db_path(tmp_path):
    """
    Create a temporary database file path for integration tests.

    Args:
        tmp_path: Pytest's temporary directory fixture.

    Returns:
        Path to temporary database file.
    """
    return str(tmp_path / "test_social_media.db")


@pytest.fixture(scope="function")
def real_database(temp_db_path):
    """
    Create a real SQLite database instance for integration testing.

    This fixture provides an actual SQLite database (file-based in temp dir)
    for testing real SQL queries and database operations.

    Args:
        temp_db_path: Path to temporary database file.

    Returns:
        SocialMediaDatabase: Real database instance.

    Example:
        def test_database_operations(real_database):
            real_database._insert_instagram_post(shortcode="ABC123", ...)
            post = real_database.get_instagram_post("ABC123")
            assert post is not None
    """
    db = SocialMediaDatabase(temp_db_path)
    yield db


@pytest.fixture(autouse=True)
def suppress_async_warnings():
    """
    Suppress known harmless warnings during async test cleanup.
    """
    warnings.filterwarnings(
        "ignore",
        category=ResourceWarning,
        message=".*coroutine.*was never awaited.*"
    )
    warnings.filterwarnings(
        "ignore",
        category=RuntimeWarning,
        message=".*Event loop is closed.*"
    )
    yield


