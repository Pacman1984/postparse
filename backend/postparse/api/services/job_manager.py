"""
Job Manager for extraction job lifecycle management.

This module provides thread-safe in-memory storage and management of extraction jobs,
tracking their status, progress, and errors throughout the extraction process.
"""

import logging
import threading
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

from backend.postparse.api.schemas.telegram import ExtractionStatus

logger = logging.getLogger(__name__)


@dataclass
class Job:
    """
    Represents an extraction job with status tracking.
    
    Attributes:
        job_id: Unique identifier for the job (UUID)
        status: Current status of the job (ExtractionStatus enum)
        progress: Progress percentage (0-100)
        messages_processed: Number of messages/posts processed so far
        errors: List of error messages encountered during extraction
        start_time: Timestamp when job was created
        end_time: Timestamp when job completed or failed
        job_type: Type of extraction ('telegram' or 'instagram')
        metadata: Additional request parameters and metadata
    
    Example:
        >>> job = Job(
        ...     job_id="550e8400-e29b-41d4-a716-446655440000",
        ...     status=ExtractionStatus.PENDING,
        ...     job_type="telegram",
        ...     metadata={"api_id": "12345", "limit": 100}
        ... )
    """
    
    job_id: str
    status: ExtractionStatus
    progress: int = 0
    messages_processed: int = 0
    errors: List[str] = field(default_factory=list)
    start_time: datetime = field(default_factory=datetime.now)
    end_time: Optional[datetime] = None
    job_type: str = ""  # 'telegram' or 'instagram'
    metadata: Dict[str, Any] = field(default_factory=dict)


class JobManager:
    """
    Thread-safe manager for extraction job lifecycle.
    
    This class provides a singleton pattern for managing extraction jobs in memory,
    with thread-safe operations for creating, updating, and retrieving job status.
    
    Example:
        >>> manager = JobManager()
        >>> job_id = manager.create_job('telegram', {'limit': 100})
        >>> manager.update_job_status(job_id, ExtractionStatus.RUNNING, 50, 50, [])
        >>> job = manager.get_job(job_id)
        >>> print(f"Progress: {job.progress}%")
        Progress: 50%
    """
    
    def __init__(self):
        """Initialize JobManager with empty job store and lock."""
        self._jobs: Dict[str, Job] = {}
        self._lock = threading.Lock()
        logger.info("JobManager initialized")
    
    def create_job(self, job_type: str, metadata: dict) -> str:
        """
        Create a new extraction job with PENDING status.
        
        Args:
            job_type: Type of extraction ('telegram' or 'instagram')
            metadata: Dictionary containing request parameters
        
        Returns:
            Generated job_id (UUID string)
        
        Example:
            >>> manager = JobManager()
            >>> job_id = manager.create_job('telegram', {
            ...     'api_id': '12345',
            ...     'api_hash': 'abc123',
            ...     'limit': 100
            ... })
        """
        job_id = str(uuid.uuid4())
        job = Job(
            job_id=job_id,
            status=ExtractionStatus.PENDING,
            job_type=job_type,
            metadata=metadata,
        )
        
        with self._lock:
            self._jobs[job_id] = job
        
        logger.info(f"Created {job_type} job {job_id}")
        return job_id
    
    def get_job(self, job_id: str) -> Optional[Job]:
        """
        Retrieve a job by its ID.
        
        Args:
            job_id: UUID string of the job
        
        Returns:
            Job object if found, None otherwise
        
        Example:
            >>> job = manager.get_job('550e8400-e29b-41d4-a716-446655440000')
            >>> if job:
            ...     print(f"Status: {job.status}")
        """
        with self._lock:
            return self._jobs.get(job_id)
    
    def update_job_status(
        self,
        job_id: str,
        status: ExtractionStatus,
        progress: int,
        messages_processed: int,
        errors: Optional[List[str]] = None,
    ) -> None:
        """
        Update job status, progress, and error information atomically.
        
        Args:
            job_id: UUID string of the job
            status: New ExtractionStatus
            progress: Progress percentage (0-100)
            messages_processed: Number of items processed so far
            errors: Optional list of error messages to append
        
        Raises:
            ValueError: If job_id not found
        
        Example:
            >>> manager.update_job_status(
            ...     job_id,
            ...     ExtractionStatus.RUNNING,
            ...     75,
            ...     150,
            ...     []
            ... )
        """
        with self._lock:
            job = self._jobs.get(job_id)
            if job is None:
                raise ValueError(f"Job {job_id} not found")
            
            job.status = status
            job.progress = min(100, max(0, progress))
            job.messages_processed = messages_processed
            
            if errors:
                job.errors.extend(errors)
        
        logger.info(
            f"Updated job {job_id}: status={status}, progress={progress}%, "
            f"processed={messages_processed}"
        )
    
    def mark_job_completed(self, job_id: str, messages_processed: int) -> None:
        """
        Mark a job as successfully completed.
        
        Args:
            job_id: UUID string of the job
            messages_processed: Final count of processed items
        
        Raises:
            ValueError: If job_id not found
        
        Example:
            >>> manager.mark_job_completed(job_id, 200)
        """
        with self._lock:
            job = self._jobs.get(job_id)
            if job is None:
                raise ValueError(f"Job {job_id} not found")
            
            job.status = ExtractionStatus.COMPLETED
            job.progress = 100
            job.messages_processed = messages_processed
            job.end_time = datetime.now()
        
        logger.info(f"Job {job_id} completed: {messages_processed} items processed")
    
    def mark_job_failed(self, job_id: str, error: str) -> None:
        """
        Mark a job as failed with error message.
        
        Args:
            job_id: UUID string of the job
            error: Error message describing the failure
        
        Raises:
            ValueError: If job_id not found
        
        Example:
            >>> manager.mark_job_failed(job_id, "Connection timeout")
        """
        with self._lock:
            job = self._jobs.get(job_id)
            if job is None:
                raise ValueError(f"Job {job_id} not found")
            
            job.status = ExtractionStatus.FAILED
            job.errors.append(error)
            job.end_time = datetime.now()
        
        logger.error(f"Job {job_id} failed: {error}")
    
    def list_jobs(self) -> List[Job]:
        """
        Retrieve all jobs (for debugging/admin purposes).
        
        Returns:
            List of all Job objects
        
        Example:
            >>> jobs = manager.list_jobs()
            >>> for job in jobs:
            ...     print(f"{job.job_id}: {job.status}")
        """
        with self._lock:
            return list(self._jobs.values())
    
    def cleanup_old_jobs(self, max_age_hours: int = 24) -> int:
        """
        Remove jobs older than specified age to prevent memory leaks.
        
        Args:
            max_age_hours: Maximum age in hours before cleanup (default: 24)
        
        Returns:
            Number of jobs cleaned up
        
        Example:
            >>> cleaned = manager.cleanup_old_jobs(max_age_hours=12)
            >>> print(f"Cleaned up {cleaned} old jobs")
        """
        cutoff_time = datetime.now() - timedelta(hours=max_age_hours)
        cleaned_count = 0
        
        with self._lock:
            jobs_to_remove = [
                job_id
                for job_id, job in self._jobs.items()
                if job.start_time < cutoff_time
            ]
            
            for job_id in jobs_to_remove:
                del self._jobs[job_id]
                cleaned_count += 1
        
        if cleaned_count > 0:
            logger.info(f"Cleaned up {cleaned_count} jobs older than {max_age_hours} hours")
        
        return cleaned_count
