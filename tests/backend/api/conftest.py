"""
Pytest fixtures for PostParse API tests.

This module provides shared fixtures for testing the FastAPI application.
"""

import pytest
from fastapi.testclient import TestClient
from backend.postparse.api.main import app


@pytest.fixture(scope="module")
def test_client():
    """
    Create a FastAPI TestClient for testing.
    
    This fixture is module-scoped to avoid recreating the client
    for every test, which would reinitialize the app multiple times.
    
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

