"""
FastAPI router for unified job status endpoints.

This module provides a platform-agnostic job status endpoint that works
for both Telegram and Instagram extraction jobs. This unified endpoint
complements the platform-specific job status endpoints for backward compatibility.
"""

from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, status, WebSocket, WebSocketDisconnect

from backend.postparse.api.dependencies import (
    get_job_manager,
    get_optional_auth,
    get_websocket_manager,
)
from backend.postparse.api.services.job_manager import JobManager
from backend.postparse.api.services.websocket_manager import WebSocketManager
from backend.postparse.api.schemas import (
    JobStatusResponse,
)

router = APIRouter(
    prefix="/api/v1/jobs",
    tags=["jobs"],
    responses={
        404: {"description": "Job not found"},
        500: {"description": "Internal server error"},
    },
)


@router.get(
    "/{job_id}",
    response_model=JobStatusResponse,
    summary="Check extraction job status",
    description="""
    Query the status of any extraction job (Telegram or Instagram).
    
    This is a unified endpoint that works for jobs from all platforms,
    providing a consistent interface for job status tracking.
    
    Returns current progress, messages/posts processed, and any errors encountered.
    """,
)
async def get_job_status(
    job_id: str,
    job_manager: JobManager = Depends(get_job_manager),
    user: Optional[dict] = Depends(get_optional_auth),
) -> JobStatusResponse:
    """
    Get extraction job status for any platform.
    
    This unified endpoint retrieves job status regardless of the platform
    (Telegram or Instagram) that initiated the job. It provides a single
    consistent API for tracking job progress.
    
    Args:
        job_id: Unique job identifier from extract request.
        job_manager: Job state manager (injected dependency).
        user: Optional authenticated user info.
        
    Returns:
        JobStatusResponse with current job status and progress.
        
    Raises:
        HTTPException: 404 if job not found.
        
    Example:
        GET /api/v1/jobs/550e8400-e29b-41d4-a716-446655440000
        
        Response:
        {
            "job_id": "550e8400-e29b-41d4-a716-446655440000",
            "status": "running",
            "progress": 65,
            "messages_processed": 65,
            "errors": []
        }
    """
    # Retrieve job from job manager
    job = job_manager.get_job(job_id)
    
    if not job:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Job {job_id} not found",
        )
    
    return JobStatusResponse(
        job_id=job.job_id,
        status=job.status,
        progress=job.progress,
        messages_processed=job.messages_processed,
        errors=job.errors,
    )


@router.websocket("/ws/progress/{job_id}")
async def websocket_progress(
    websocket: WebSocket,
    job_id: str,
    ws_manager: WebSocketManager = Depends(get_websocket_manager),
    job_manager: JobManager = Depends(get_job_manager),
):
    """
    Unified WebSocket endpoint for real-time job progress updates.
    
    This endpoint provides a platform-agnostic way to receive live progress
    updates for any extraction job (Telegram or Instagram). Clients can connect
    to this endpoint and receive JSON messages with job status, progress percentage,
    and messages/posts processed.
    
    This is the recommended endpoint for WebSocket connections. Platform-specific
    endpoints (/api/v1/telegram/ws/progress/{job_id} and /api/v1/instagram/ws/progress/{job_id})
    are maintained for backward compatibility but provide identical functionality.
    
    Args:
        websocket: WebSocket connection.
        job_id: Unique job identifier.
        ws_manager: WebSocket manager (injected dependency).
        job_manager: Job state manager (injected dependency).
        
    Example:
        const ws = new WebSocket('ws://localhost:8000/api/v1/jobs/ws/progress/550e8400-e29b-41d4-a716-446655440000');
        
        ws.onmessage = (event) => {
            const data = JSON.parse(event.data);
            console.log(`Progress: ${data.progress}%`);
        };
        
    Message Format:
        {
            "job_id": "550e8400-e29b-41d4-a716-446655440000",
            "status": "running",
            "progress": 65,
            "messages_processed": 65,
            "errors": [],
            "timestamp": "2025-11-23T10:30:00Z"
        }
    """
    # Verify job exists
    job = job_manager.get_job(job_id)
    if not job:
        await websocket.accept()
        await websocket.send_json({
            "error": f"Job {job_id} not found",
            "job_id": job_id
        })
        await websocket.close()
        return
    
    # Register connection
    await ws_manager.connect(job_id, websocket)
    
    # Send initial job status
    await ws_manager.send_job_update(job_id, job)
    
    try:
        # Keep connection alive and listen for disconnect
        while True:
            # Wait for messages (client may send ping/keepalive)
            await websocket.receive_text()
    except WebSocketDisconnect:
        # Client disconnected
        await ws_manager.disconnect(job_id, websocket)
    except Exception as e:
        # Handle other errors
        await ws_manager.disconnect(job_id, websocket)

