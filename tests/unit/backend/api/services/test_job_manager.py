"""
Unit tests for JobManager class.

This module provides comprehensive tests for the JobManager service which handles
extraction job lifecycle management with thread-safe operations.
"""

from datetime import datetime, timedelta
from typing import List
from unittest.mock import patch
import threading
import time

import pytest

from backend.postparse.api.services.job_manager import Job, JobManager
from backend.postparse.api.schemas.telegram import ExtractionStatus


class TestJobDataclass:
    """Tests for Job dataclass."""

    def test_job_creation_with_required_fields(self) -> None:
        """
        Test creating a Job with only required fields.

        Verifies default values are set correctly for optional fields.
        """
        job = Job(
            job_id="test-uuid-123",
            status=ExtractionStatus.PENDING,
        )

        assert job.job_id == "test-uuid-123"
        assert job.status == ExtractionStatus.PENDING
        assert job.progress == 0
        assert job.messages_processed == 0
        assert job.errors == []
        assert job.job_type == ""
        assert job.metadata == {}
        assert job.end_time is None
        assert isinstance(job.start_time, datetime)

    def test_job_creation_with_all_fields(self) -> None:
        """
        Test creating a Job with all fields specified.

        Verifies all provided values are stored correctly.
        """
        start_time = datetime(2024, 1, 15, 10, 0, 0)
        end_time = datetime(2024, 1, 15, 10, 30, 0)
        metadata = {"api_id": "12345", "limit": 100}
        errors = ["Error 1", "Error 2"]

        job = Job(
            job_id="test-uuid-456",
            status=ExtractionStatus.COMPLETED,
            progress=100,
            messages_processed=500,
            errors=errors,
            start_time=start_time,
            end_time=end_time,
            job_type="telegram",
            metadata=metadata,
        )

        assert job.job_id == "test-uuid-456"
        assert job.status == ExtractionStatus.COMPLETED
        assert job.progress == 100
        assert job.messages_processed == 500
        assert job.errors == errors
        assert job.start_time == start_time
        assert job.end_time == end_time
        assert job.job_type == "telegram"
        assert job.metadata == metadata

    def test_job_errors_list_is_mutable(self) -> None:
        """
        Test that the errors list can be modified after creation.

        Verifies errors can be appended during job execution.
        """
        job = Job(
            job_id="test-uuid-789",
            status=ExtractionStatus.RUNNING,
        )

        job.errors.append("New error")
        assert len(job.errors) == 1
        assert job.errors[0] == "New error"

    def test_job_default_factory_creates_independent_lists(self) -> None:
        """
        Test that each Job has independent errors and metadata dicts.

        Verifies default_factory creates new instances for each Job.
        """
        job1 = Job(job_id="job1", status=ExtractionStatus.PENDING)
        job2 = Job(job_id="job2", status=ExtractionStatus.PENDING)

        job1.errors.append("error for job1")
        job1.metadata["key"] = "value"

        assert job2.errors == []
        assert job2.metadata == {}


class TestJobManagerInitialization:
    """Tests for JobManager initialization."""

    def test_manager_initialization(self) -> None:
        """
        Test JobManager initializes with empty job store.

        Verifies initial state is correctly set up.
        """
        manager = JobManager()

        assert manager._jobs == {}
        assert isinstance(manager._lock, type(threading.Lock()))

    def test_manager_has_thread_lock(self) -> None:
        """
        Test JobManager has a threading lock for concurrency.

        Verifies thread-safety mechanism is in place.
        """
        manager = JobManager()

        # Lock should be acquirable
        acquired = manager._lock.acquire(blocking=False)
        assert acquired
        manager._lock.release()


class TestJobManagerCreateJob:
    """Tests for JobManager.create_job()."""

    def test_create_job_returns_uuid_string(self) -> None:
        """
        Test create_job returns a valid UUID string.

        Verifies the returned job_id is a properly formatted UUID.
        """
        manager = JobManager()
        job_id = manager.create_job("telegram", {"limit": 100})

        assert isinstance(job_id, str)
        assert len(job_id) == 36  # UUID format: 8-4-4-4-12

    def test_create_job_stores_job_with_pending_status(self) -> None:
        """
        Test create_job creates a job with PENDING status.

        Verifies initial job state is correct.
        """
        manager = JobManager()
        job_id = manager.create_job("telegram", {"limit": 100})

        job = manager.get_job(job_id)
        assert job is not None
        assert job.status == ExtractionStatus.PENDING

    def test_create_job_stores_job_type(self) -> None:
        """
        Test create_job correctly stores the job type.

        Verifies job_type is set for telegram and instagram.
        """
        manager = JobManager()

        telegram_job_id = manager.create_job("telegram", {})
        instagram_job_id = manager.create_job("instagram", {})

        telegram_job = manager.get_job(telegram_job_id)
        instagram_job = manager.get_job(instagram_job_id)

        assert telegram_job.job_type == "telegram"
        assert instagram_job.job_type == "instagram"

    def test_create_job_stores_metadata(self) -> None:
        """
        Test create_job correctly stores metadata.

        Verifies metadata dictionary is preserved.
        """
        manager = JobManager()
        metadata = {"api_id": "12345", "api_hash": "abc123", "limit": 100}
        job_id = manager.create_job("telegram", metadata)

        job = manager.get_job(job_id)
        assert job.metadata == metadata

    def test_create_job_generates_unique_ids(self) -> None:
        """
        Test create_job generates unique IDs for each job.

        Verifies multiple jobs have distinct UUIDs.
        """
        manager = JobManager()
        job_ids = [manager.create_job("telegram", {}) for _ in range(10)]

        # All IDs should be unique
        assert len(set(job_ids)) == 10

    def test_create_job_sets_start_time(self) -> None:
        """
        Test create_job sets start_time to current time.

        Verifies start_time is set during job creation.
        """
        manager = JobManager()
        before = datetime.now()
        job_id = manager.create_job("telegram", {})
        after = datetime.now()

        job = manager.get_job(job_id)
        assert before <= job.start_time <= after


class TestJobManagerGetJob:
    """Tests for JobManager.get_job()."""

    def test_get_job_returns_existing_job(self) -> None:
        """
        Test get_job returns the correct job for valid ID.

        Verifies job retrieval works correctly.
        """
        manager = JobManager()
        job_id = manager.create_job("telegram", {"key": "value"})

        job = manager.get_job(job_id)

        assert job is not None
        assert job.job_id == job_id
        assert job.metadata == {"key": "value"}

    def test_get_job_returns_none_for_nonexistent_id(self) -> None:
        """
        Test get_job returns None for unknown job ID.

        Verifies graceful handling of missing jobs.
        """
        manager = JobManager()

        job = manager.get_job("nonexistent-uuid")

        assert job is None

    def test_get_job_returns_none_for_empty_store(self) -> None:
        """
        Test get_job returns None when no jobs exist.

        Verifies correct behavior with empty job store.
        """
        manager = JobManager()

        job = manager.get_job("any-uuid")

        assert job is None


class TestJobManagerUpdateJobStatus:
    """Tests for JobManager.update_job_status()."""

    def test_update_job_status_changes_status(self) -> None:
        """
        Test update_job_status changes job status.

        Verifies status is updated correctly.
        """
        manager = JobManager()
        job_id = manager.create_job("telegram", {})

        manager.update_job_status(job_id, ExtractionStatus.RUNNING, 50, 100, None)

        job = manager.get_job(job_id)
        assert job.status == ExtractionStatus.RUNNING

    def test_update_job_status_sets_progress(self) -> None:
        """
        Test update_job_status sets progress percentage.

        Verifies progress is updated correctly.
        """
        manager = JobManager()
        job_id = manager.create_job("telegram", {})

        manager.update_job_status(job_id, ExtractionStatus.RUNNING, 75, 150, None)

        job = manager.get_job(job_id)
        assert job.progress == 75

    def test_update_job_status_clamps_progress_to_100(self) -> None:
        """
        Test update_job_status clamps progress to max 100.

        Verifies progress doesn't exceed 100%.
        """
        manager = JobManager()
        job_id = manager.create_job("telegram", {})

        manager.update_job_status(job_id, ExtractionStatus.RUNNING, 150, 100, None)

        job = manager.get_job(job_id)
        assert job.progress == 100

    def test_update_job_status_clamps_progress_to_0(self) -> None:
        """
        Test update_job_status clamps progress to min 0.

        Verifies progress doesn't go below 0%.
        """
        manager = JobManager()
        job_id = manager.create_job("telegram", {})

        manager.update_job_status(job_id, ExtractionStatus.RUNNING, -10, 0, None)

        job = manager.get_job(job_id)
        assert job.progress == 0

    def test_update_job_status_sets_messages_processed(self) -> None:
        """
        Test update_job_status sets messages_processed count.

        Verifies message count is updated correctly.
        """
        manager = JobManager()
        job_id = manager.create_job("telegram", {})

        manager.update_job_status(job_id, ExtractionStatus.RUNNING, 50, 250, None)

        job = manager.get_job(job_id)
        assert job.messages_processed == 250

    def test_update_job_status_appends_errors(self) -> None:
        """
        Test update_job_status appends new errors to existing errors.

        Verifies errors are accumulated, not replaced.
        """
        manager = JobManager()
        job_id = manager.create_job("telegram", {})

        manager.update_job_status(
            job_id, ExtractionStatus.RUNNING, 25, 50, ["Error 1"]
        )
        manager.update_job_status(
            job_id, ExtractionStatus.RUNNING, 50, 100, ["Error 2", "Error 3"]
        )

        job = manager.get_job(job_id)
        assert job.errors == ["Error 1", "Error 2", "Error 3"]

    def test_update_job_status_raises_for_nonexistent_job(self) -> None:
        """
        Test update_job_status raises ValueError for unknown job.

        Verifies proper error handling for invalid job ID.
        """
        manager = JobManager()

        with pytest.raises(ValueError, match="Job .* not found"):
            manager.update_job_status(
                "nonexistent-uuid", ExtractionStatus.RUNNING, 50, 100, None
            )


class TestJobManagerMarkJobCompleted:
    """Tests for JobManager.mark_job_completed()."""

    def test_mark_job_completed_sets_completed_status(self) -> None:
        """
        Test mark_job_completed sets status to COMPLETED.

        Verifies status change on completion.
        """
        manager = JobManager()
        job_id = manager.create_job("telegram", {})

        manager.mark_job_completed(job_id, 500)

        job = manager.get_job(job_id)
        assert job.status == ExtractionStatus.COMPLETED

    def test_mark_job_completed_sets_progress_to_100(self) -> None:
        """
        Test mark_job_completed sets progress to 100%.

        Verifies progress is set to complete.
        """
        manager = JobManager()
        job_id = manager.create_job("telegram", {})

        manager.mark_job_completed(job_id, 500)

        job = manager.get_job(job_id)
        assert job.progress == 100

    def test_mark_job_completed_sets_messages_processed(self) -> None:
        """
        Test mark_job_completed sets final messages_processed count.

        Verifies final count is stored.
        """
        manager = JobManager()
        job_id = manager.create_job("telegram", {})

        manager.mark_job_completed(job_id, 1234)

        job = manager.get_job(job_id)
        assert job.messages_processed == 1234

    def test_mark_job_completed_sets_end_time(self) -> None:
        """
        Test mark_job_completed sets end_time to current time.

        Verifies end_time is recorded on completion.
        """
        manager = JobManager()
        job_id = manager.create_job("telegram", {})

        before = datetime.now()
        manager.mark_job_completed(job_id, 500)
        after = datetime.now()

        job = manager.get_job(job_id)
        assert job.end_time is not None
        assert before <= job.end_time <= after

    def test_mark_job_completed_raises_for_nonexistent_job(self) -> None:
        """
        Test mark_job_completed raises ValueError for unknown job.

        Verifies proper error handling for invalid job ID.
        """
        manager = JobManager()

        with pytest.raises(ValueError, match="Job .* not found"):
            manager.mark_job_completed("nonexistent-uuid", 100)


class TestJobManagerMarkJobFailed:
    """Tests for JobManager.mark_job_failed()."""

    def test_mark_job_failed_sets_failed_status(self) -> None:
        """
        Test mark_job_failed sets status to FAILED.

        Verifies status change on failure.
        """
        manager = JobManager()
        job_id = manager.create_job("telegram", {})

        manager.mark_job_failed(job_id, "Connection timeout")

        job = manager.get_job(job_id)
        assert job.status == ExtractionStatus.FAILED

    def test_mark_job_failed_appends_error_message(self) -> None:
        """
        Test mark_job_failed appends the error message to errors list.

        Verifies error message is recorded.
        """
        manager = JobManager()
        job_id = manager.create_job("telegram", {})

        manager.mark_job_failed(job_id, "Authentication failed")

        job = manager.get_job(job_id)
        assert "Authentication failed" in job.errors

    def test_mark_job_failed_preserves_existing_errors(self) -> None:
        """
        Test mark_job_failed preserves existing errors.

        Verifies error accumulation.
        """
        manager = JobManager()
        job_id = manager.create_job("telegram", {})
        manager.update_job_status(
            job_id, ExtractionStatus.RUNNING, 25, 50, ["Warning 1"]
        )

        manager.mark_job_failed(job_id, "Fatal error")

        job = manager.get_job(job_id)
        assert "Warning 1" in job.errors
        assert "Fatal error" in job.errors

    def test_mark_job_failed_sets_end_time(self) -> None:
        """
        Test mark_job_failed sets end_time to current time.

        Verifies end_time is recorded on failure.
        """
        manager = JobManager()
        job_id = manager.create_job("telegram", {})

        before = datetime.now()
        manager.mark_job_failed(job_id, "Error")
        after = datetime.now()

        job = manager.get_job(job_id)
        assert job.end_time is not None
        assert before <= job.end_time <= after

    def test_mark_job_failed_raises_for_nonexistent_job(self) -> None:
        """
        Test mark_job_failed raises ValueError for unknown job.

        Verifies proper error handling for invalid job ID.
        """
        manager = JobManager()

        with pytest.raises(ValueError, match="Job .* not found"):
            manager.mark_job_failed("nonexistent-uuid", "Error")


class TestJobManagerListJobs:
    """Tests for JobManager.list_jobs()."""

    def test_list_jobs_returns_empty_list_when_no_jobs(self) -> None:
        """
        Test list_jobs returns empty list when no jobs exist.

        Verifies correct behavior with empty job store.
        """
        manager = JobManager()

        jobs = manager.list_jobs()

        assert jobs == []

    def test_list_jobs_returns_all_jobs(self) -> None:
        """
        Test list_jobs returns all created jobs.

        Verifies all jobs are included in the list.
        """
        manager = JobManager()
        job_ids = [
            manager.create_job("telegram", {"id": 1}),
            manager.create_job("instagram", {"id": 2}),
            manager.create_job("telegram", {"id": 3}),
        ]

        jobs = manager.list_jobs()

        assert len(jobs) == 3
        returned_ids = [job.job_id for job in jobs]
        for job_id in job_ids:
            assert job_id in returned_ids

    def test_list_jobs_returns_jobs_with_various_statuses(self) -> None:
        """
        Test list_jobs includes jobs in all statuses.

        Verifies jobs aren't filtered by status.
        """
        manager = JobManager()
        job_id1 = manager.create_job("telegram", {})
        job_id2 = manager.create_job("telegram", {})
        job_id3 = manager.create_job("telegram", {})

        manager.update_job_status(job_id1, ExtractionStatus.RUNNING, 50, 100, None)
        manager.mark_job_completed(job_id2, 200)
        manager.mark_job_failed(job_id3, "Error")

        jobs = manager.list_jobs()
        statuses = [job.status for job in jobs]

        assert ExtractionStatus.RUNNING in statuses
        assert ExtractionStatus.COMPLETED in statuses
        assert ExtractionStatus.FAILED in statuses


class TestJobManagerCleanupOldJobs:
    """Tests for JobManager.cleanup_old_jobs()."""

    def test_cleanup_old_jobs_removes_old_jobs(self) -> None:
        """
        Test cleanup_old_jobs removes jobs older than max_age.

        Verifies old jobs are deleted.
        """
        manager = JobManager()
        job_id = manager.create_job("telegram", {})

        # Manually set start_time to old date
        with manager._lock:
            manager._jobs[job_id].start_time = datetime.now() - timedelta(hours=25)

        cleaned = manager.cleanup_old_jobs(max_age_hours=24)

        assert cleaned == 1
        assert manager.get_job(job_id) is None

    def test_cleanup_old_jobs_keeps_recent_jobs(self) -> None:
        """
        Test cleanup_old_jobs keeps jobs newer than max_age.

        Verifies recent jobs are preserved.
        """
        manager = JobManager()
        job_id = manager.create_job("telegram", {})

        cleaned = manager.cleanup_old_jobs(max_age_hours=24)

        assert cleaned == 0
        assert manager.get_job(job_id) is not None

    def test_cleanup_old_jobs_returns_count_of_removed_jobs(self) -> None:
        """
        Test cleanup_old_jobs returns correct count of removed jobs.

        Verifies accurate cleanup count.
        """
        manager = JobManager()
        old_time = datetime.now() - timedelta(hours=25)

        # Create 3 old jobs and 2 new jobs
        for i in range(5):
            job_id = manager.create_job("telegram", {"id": i})
            if i < 3:
                with manager._lock:
                    manager._jobs[job_id].start_time = old_time

        cleaned = manager.cleanup_old_jobs(max_age_hours=24)

        assert cleaned == 3
        assert len(manager.list_jobs()) == 2

    def test_cleanup_old_jobs_with_custom_max_age(self) -> None:
        """
        Test cleanup_old_jobs respects custom max_age_hours.

        Verifies custom age threshold works correctly.
        """
        manager = JobManager()
        job_id = manager.create_job("telegram", {})

        # Set job to 6 hours old
        with manager._lock:
            manager._jobs[job_id].start_time = datetime.now() - timedelta(hours=6)

        # Should NOT be cleaned with 12 hour max age
        cleaned = manager.cleanup_old_jobs(max_age_hours=12)
        assert cleaned == 0

        # Should be cleaned with 5 hour max age
        cleaned = manager.cleanup_old_jobs(max_age_hours=5)
        assert cleaned == 1

    def test_cleanup_old_jobs_returns_zero_when_empty(self) -> None:
        """
        Test cleanup_old_jobs returns 0 when no jobs exist.

        Verifies correct behavior with empty job store.
        """
        manager = JobManager()

        cleaned = manager.cleanup_old_jobs(max_age_hours=24)

        assert cleaned == 0


class TestJobManagerThreadSafety:
    """Tests for JobManager thread safety."""

    def test_concurrent_job_creation(self) -> None:
        """
        Test concurrent job creation is thread-safe.

        Verifies no race conditions during parallel job creation.
        """
        manager = JobManager()
        job_ids: List[str] = []
        lock = threading.Lock()

        def create_job():
            job_id = manager.create_job("telegram", {})
            with lock:
                job_ids.append(job_id)

        threads = [threading.Thread(target=create_job) for _ in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        # All job IDs should be unique
        assert len(set(job_ids)) == 10
        # All jobs should exist
        for job_id in job_ids:
            assert manager.get_job(job_id) is not None

    def test_concurrent_status_updates(self) -> None:
        """
        Test concurrent status updates are thread-safe.

        Verifies no race conditions during parallel updates.
        """
        manager = JobManager()
        job_id = manager.create_job("telegram", {})

        def update_progress(progress: int):
            manager.update_job_status(
                job_id, ExtractionStatus.RUNNING, progress, progress * 10, None
            )

        threads = [
            threading.Thread(target=update_progress, args=(i * 10,))
            for i in range(10)
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        # Job should still exist and have valid state
        job = manager.get_job(job_id)
        assert job is not None
        assert 0 <= job.progress <= 100


