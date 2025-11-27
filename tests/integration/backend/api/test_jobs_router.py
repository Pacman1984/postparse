"""
Tests for unified jobs router endpoints.

This module tests the platform-agnostic job status endpoint that works
for both Telegram and Instagram extraction jobs.
"""

import pytest
from fastapi.testclient import TestClient

from backend.postparse.api.main import app
from backend.postparse.api.dependencies import get_job_manager
from backend.postparse.api.services.job_manager import JobManager
from backend.postparse.api.schemas.telegram import ExtractionStatus


class TestUnifiedJobsRouter:
    """
    Test suite for unified jobs router endpoints.
    
    Tests the GET /api/v1/jobs/{job_id} endpoint that provides
    platform-agnostic job status tracking.
    """
    
    @pytest.fixture
    def job_manager(self) -> JobManager:
        """
        Create JobManager instance for managing test jobs.
        
        This fixture overrides the dependency injection to ensure
        the test and the endpoint use the same JobManager instance.
        
        Returns:
            JobManager instance.
            
        Example:
            >>> def test_something(self, job_manager, client):
            ...     job_id = job_manager.create_job('telegram', {})
        """
        return JobManager()
    
    @pytest.fixture
    def client(self, job_manager: JobManager) -> TestClient:
        """
        Create test client with overridden dependencies.
        
        This fixture overrides the get_job_manager dependency to use
        the same JobManager instance created in the job_manager fixture.
        
        Args:
            job_manager: JobManager instance from fixture.
        
        Returns:
            TestClient instance for making API calls.
            
        Example:
            >>> def test_something(self, client):
            ...     response = client.get('/api/v1/jobs/123')
        """
        # Override the get_job_manager dependency
        app.dependency_overrides[get_job_manager] = lambda: job_manager
        
        client = TestClient(app)
        yield client
        
        # Clean up after test
        app.dependency_overrides.clear()
    
    def test_get_job_status_telegram_job(
        self, 
        client: TestClient, 
        job_manager: JobManager
    ) -> None:
        """
        Test GET /api/v1/jobs/{job_id} for Telegram extraction job.
        
        Verifies that the unified endpoint correctly retrieves status
        for a Telegram extraction job.
        
        Args:
            client: Test client fixture.
            job_manager: Job manager fixture.
            
        Example:
            Create Telegram job, query status via unified endpoint,
            expect 200 with correct job details.
        """
        # Create a Telegram job
        job_id = job_manager.create_job('telegram', {
            'api_id': 12345678,
            'api_hash': 'test_hash',
            'phone': '+1234567890',
            'limit': 100
        })
        
        # Query job status via unified endpoint
        response = client.get(f"/api/v1/jobs/{job_id}")
        
        # Verify response
        assert response.status_code == 200
        data = response.json()
        assert data["job_id"] == job_id
        assert data["status"] == ExtractionStatus.PENDING
        assert data["progress"] == 0
        assert data["messages_processed"] == 0
        assert data["errors"] == []
    
    def test_get_job_status_instagram_job(
        self, 
        client: TestClient, 
        job_manager: JobManager
    ) -> None:
        """
        Test GET /api/v1/jobs/{job_id} for Instagram extraction job.
        
        Verifies that the unified endpoint correctly retrieves status
        for an Instagram extraction job.
        
        Args:
            client: Test client fixture.
            job_manager: Job manager fixture.
            
        Example:
            Create Instagram job, query status via unified endpoint,
            expect 200 with correct job details.
        """
        # Create an Instagram job
        job_id = job_manager.create_job('instagram', {
            'username': 'test_user',
            'password': 'test_password',
            'limit': 50
        })
        
        # Query job status via unified endpoint
        response = client.get(f"/api/v1/jobs/{job_id}")
        
        # Verify response
        assert response.status_code == 200
        data = response.json()
        assert data["job_id"] == job_id
        assert data["status"] == ExtractionStatus.PENDING
        assert data["progress"] == 0
        assert data["messages_processed"] == 0
        assert data["errors"] == []
    
    def test_get_job_status_not_found(self, client: TestClient) -> None:
        """
        Test GET /api/v1/jobs/{job_id} with non-existent job ID.
        
        Verifies that the endpoint returns 404 when job is not found.
        
        Args:
            client: Test client fixture.
            
        Example:
            Query non-existent job, expect 404 with error message.
        """
        # Query non-existent job
        fake_job_id = "550e8400-e29b-41d4-a716-446655440000"
        response = client.get(f"/api/v1/jobs/{fake_job_id}")
        
        # Verify 404 response
        assert response.status_code == 404
        data = response.json()
        assert "not found" in data["detail"].lower()
    
    def test_get_job_status_running(
        self, 
        client: TestClient, 
        job_manager: JobManager
    ) -> None:
        """
        Test GET /api/v1/jobs/{job_id} for running job.
        
        Verifies that the endpoint correctly reports progress for
        a job that is currently running.
        
        Args:
            client: Test client fixture.
            job_manager: Job manager fixture.
            
        Example:
            Create job, update to running with progress, query status,
            expect correct progress and status.
        """
        # Create job and update to running state
        job_id = job_manager.create_job('telegram', {})
        job_manager.update_job_status(
            job_id,
            ExtractionStatus.RUNNING,
            progress=50,
            messages_processed=50,
            errors=[]
        )
        
        # Query job status
        response = client.get(f"/api/v1/jobs/{job_id}")
        
        # Verify response reflects running state
        assert response.status_code == 200
        data = response.json()
        assert data["job_id"] == job_id
        assert data["status"] == ExtractionStatus.RUNNING
        assert data["progress"] == 50
        assert data["messages_processed"] == 50
        assert data["errors"] == []
    
    def test_get_job_status_completed(
        self, 
        client: TestClient, 
        job_manager: JobManager
    ) -> None:
        """
        Test GET /api/v1/jobs/{job_id} for completed job.
        
        Verifies that the endpoint correctly reports completion status.
        
        Args:
            client: Test client fixture.
            job_manager: Job manager fixture.
            
        Example:
            Create job, mark as completed, query status,
            expect completed status with 100% progress.
        """
        # Create job and mark as completed
        job_id = job_manager.create_job('instagram', {})
        job_manager.mark_job_completed(job_id, messages_processed=100)
        
        # Query job status
        response = client.get(f"/api/v1/jobs/{job_id}")
        
        # Verify completion status
        assert response.status_code == 200
        data = response.json()
        assert data["job_id"] == job_id
        assert data["status"] == ExtractionStatus.COMPLETED
        assert data["progress"] == 100
        assert data["messages_processed"] == 100
        assert data["errors"] == []
    
    def test_get_job_status_failed(
        self, 
        client: TestClient, 
        job_manager: JobManager
    ) -> None:
        """
        Test GET /api/v1/jobs/{job_id} for failed job.
        
        Verifies that the endpoint correctly reports failure status
        with error messages.
        
        Args:
            client: Test client fixture.
            job_manager: Job manager fixture.
            
        Example:
            Create job, mark as failed with error, query status,
            expect failed status with error message.
        """
        # Create job and mark as failed
        job_id = job_manager.create_job('telegram', {})
        error_message = "Connection timeout"
        job_manager.mark_job_failed(job_id, error_message)
        
        # Query job status
        response = client.get(f"/api/v1/jobs/{job_id}")
        
        # Verify failure status
        assert response.status_code == 200
        data = response.json()
        assert data["job_id"] == job_id
        assert data["status"] == ExtractionStatus.FAILED
        assert error_message in data["errors"]
    
    def test_platform_specific_endpoints_still_work(
        self, 
        client: TestClient, 
        job_manager: JobManager
    ) -> None:
        """
        Test backward compatibility with platform-specific endpoints.
        
        Verifies that the existing Telegram and Instagram job status
        endpoints still work alongside the unified endpoint, returning
        identical payloads.
        
        Args:
            client: Test client fixture.
            job_manager: Job manager fixture.
            
        Example:
            Create Telegram job, query via both unified and Telegram-specific
            endpoints, expect identical responses.
        """
        # Create Telegram job
        telegram_job_id = job_manager.create_job('telegram', {})
        
        # Query via unified endpoint
        unified_response = client.get(f"/api/v1/jobs/{telegram_job_id}")
        
        # Query via platform-specific endpoint
        telegram_response = client.get(f"/api/v1/telegram/jobs/{telegram_job_id}")
        
        # Verify both endpoints return the same data
        assert unified_response.status_code == 200
        assert telegram_response.status_code == 200
        assert unified_response.json() == telegram_response.json()
        
        # Create Instagram job
        instagram_job_id = job_manager.create_job('instagram', {})
        
        # Query via unified endpoint
        unified_response = client.get(f"/api/v1/jobs/{instagram_job_id}")
        
        # Query via platform-specific endpoint
        instagram_response = client.get(f"/api/v1/instagram/jobs/{instagram_job_id}")
        
        # Verify both endpoints return the same data
        assert unified_response.status_code == 200
        assert instagram_response.status_code == 200
        assert unified_response.json() == instagram_response.json()

