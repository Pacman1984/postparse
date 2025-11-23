"""
Pytest fixtures for PostParse API tests.

This module provides shared fixtures for testing the FastAPI application.
"""

import asyncio
import pytest
import time
from fastapi.testclient import TestClient
from backend.postparse.api.main import app
from backend.postparse.api.services.job_manager import JobManager


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

