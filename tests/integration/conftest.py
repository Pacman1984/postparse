"""
Pytest configuration for integration tests.

Integration tests test the interaction between multiple components
and may use real databases (in-memory SQLite) and services.
"""

import warnings

import pytest


@pytest.fixture(autouse=True)
def suppress_async_warnings():
    """
    Suppress known harmless warnings during async test cleanup.
    """
    warnings.filterwarnings(
        "ignore", category=ResourceWarning, message=".*coroutine.*was never awaited.*"
    )
    warnings.filterwarnings("ignore", category=RuntimeWarning, message=".*Event loop is closed.*")
    yield
