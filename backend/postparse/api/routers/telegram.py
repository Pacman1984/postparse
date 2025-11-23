"""
FastAPI router for Telegram extraction endpoints.

This module provides HTTP endpoints for triggering Telegram message extraction,
checking job status, and retrieving extracted messages.

Note: Actual extraction logic with background tasks will be implemented in
the next phase. This module contains placeholder implementations.
"""

import uuid
from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, Query, status, BackgroundTasks, WebSocket, WebSocketDisconnect

from backend.postparse.core.data.database import SocialMediaDatabase
from backend.postparse.api.dependencies import (
    get_db,
    get_optional_auth,
    get_job_manager,
    get_websocket_manager,
    get_telegram_extraction_service,
)
from backend.postparse.api.services.job_manager import JobManager
from backend.postparse.api.services.websocket_manager import WebSocketManager
from backend.postparse.api.services.extraction_service import TelegramExtractionService
from backend.postparse.api.schemas import (
    TelegramExtractRequest,
    TelegramExtractResponse,
    TelegramMessageSchema,
    JobStatusResponse,
    ExtractionStatus,
    PaginatedResponse,
)

router = APIRouter(
    prefix="/api/v1/telegram",
    tags=["telegram"],
    responses={
        400: {"description": "Invalid request"},
        401: {"description": "Unauthorized"},
        404: {"description": "Resource not found"},
        500: {"description": "Internal server error"},
        503: {"description": "Service unavailable"},
    },
)


@router.post(
    "/extract",
    response_model=TelegramExtractResponse,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Trigger Telegram message extraction",
    description="""
    Start an async extraction job for Telegram messages.
    
    This endpoint initiates a background job that will:
    1. Authenticate with Telegram using provided credentials
    2. Extract messages from configured channels
    3. Parse and store messages in the database
    
    Returns a job_id for tracking extraction progress.
    
    Note: Actual extraction logic will be implemented in the next phase.
    """,
)
async def extract_messages(
    request: TelegramExtractRequest,
    background_tasks: BackgroundTasks,
    job_manager: JobManager = Depends(get_job_manager),
    extraction_service: TelegramExtractionService = Depends(get_telegram_extraction_service),
    user: Optional[dict] = Depends(get_optional_auth),
) -> TelegramExtractResponse:
    """
    Trigger Telegram message extraction with background processing.
    
    Args:
        request: Extraction request with Telegram credentials and options.
        background_tasks: FastAPI background tasks manager.
        job_manager: Job state manager (injected dependency).
        extraction_service: Extraction service (injected dependency).
        user: Optional authenticated user info.
        
    Returns:
        TelegramExtractResponse with job_id for tracking.
        
    Example:
        POST /api/v1/telegram/extract
        {
            "api_id": 12345678,
            "api_hash": "0123456789abcdef0123456789abcdef",
            "phone": "+1234567890",
            "limit": 100
        }
        
        Response:
        {
            "job_id": "550e8400-e29b-41d4-a716-446655440000",
            "status": "pending",
            "message_count": 0,
            "estimated_time": 60
        }
    """
    # Create job in job manager
    job_id = job_manager.create_job('telegram', request.model_dump())
    
    # Add extraction task to background tasks
    # BackgroundTasks supports async functions, so we can add the async method directly
    background_tasks.add_task(
        extraction_service.run_extraction,
        job_id=job_id,
        api_id=request.api_id,
        api_hash=request.api_hash,
        phone=request.phone,
        limit=request.limit,
        force_update=request.force_update,
        max_requests_per_session=request.max_requests_per_session,
    )
    
    return TelegramExtractResponse(
        job_id=job_id,
        status=ExtractionStatus.PENDING,
        message_count=0,
        estimated_time=60,
    )


@router.get(
    "/jobs/{job_id}",
    response_model=JobStatusResponse,
    summary="Check extraction job status",
    description="""
    Query the status of a Telegram extraction job.
    
    Returns current progress, messages processed, and any errors encountered.
    """,
)
async def get_job_status(
    job_id: str,
    job_manager: JobManager = Depends(get_job_manager),
    user: Optional[dict] = Depends(get_optional_auth),
) -> JobStatusResponse:
    """
    Get extraction job status.
    
    Args:
        job_id: Unique job identifier from extract_messages.
        job_manager: Job state manager (injected dependency).
        user: Optional authenticated user info.
        
    Returns:
        JobStatusResponse with current job status and progress.
        
    Raises:
        HTTPException: 404 if job not found.
        
    Example:
        GET /api/v1/telegram/jobs/550e8400-e29b-41d4-a716-446655440000
        
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


@router.get(
    "/messages",
    response_model=PaginatedResponse[TelegramMessageSchema],
    summary="List extracted Telegram messages",
    description="""
    Retrieve extracted Telegram messages with pagination.
    
    Currently supports basic pagination via limit parameter.
    
    Note: Advanced filtering (channel_username, offset, date range, content type) 
    is planned for a future phase and is not yet implemented.
    """,
)
async def get_messages(
    limit: int = Query(default=50, ge=1, le=100, description="Maximum results to return"),
    offset: int = Query(default=0, ge=0, description="Number of results to skip (not yet implemented)"),
    channel_username: Optional[str] = Query(default=None, description="Filter by channel (not yet implemented)"),
    db: SocialMediaDatabase = Depends(get_db),
    user: Optional[dict] = Depends(get_optional_auth),
) -> PaginatedResponse[TelegramMessageSchema]:
    """
    List extracted Telegram messages with pagination.
    
    Currently returns messages ordered by creation date (newest first) with basic limit-based pagination.
    The offset and channel_username parameters are accepted but not yet implemented.
    
    Args:
        limit: Maximum number of messages to return.
        offset: Number of messages to skip (accepted but not yet implemented).
        channel_username: Optional channel filter (accepted but not yet implemented).
        db: Database instance (injected dependency).
        user: Optional authenticated user info.
        
    Returns:
        PaginatedResponse with list of messages and pagination metadata.
        
    Example:
        GET /api/v1/telegram/messages?limit=20
        
        Response:
        {
            "items": [...],
            "total": 20,
            "limit": 20,
            "offset": 0,
            "next_cursor": null,
            "has_more": true
        }
    """
    # Use database method to retrieve messages
    # Note: offset and channel_username filters are not yet implemented
    from datetime import datetime as dt
    import json
    
    messages = db.get_telegram_messages(limit=limit + 1)  # Get one extra to check if more exist
    
    # Convert to schema objects
    message_schemas = []
    for msg in messages[:limit]:
        # Parse media_urls from JSON string if needed
        media_urls = msg.get("media_urls", [])
        if isinstance(media_urls, str):
            try:
                media_urls = json.loads(media_urls) if media_urls else []
            except json.JSONDecodeError:
                media_urls = []
        
        # Parse created_at timestamp
        created_at = msg.get("created_at")
        if created_at and isinstance(created_at, str):
            try:
                created_at = dt.fromisoformat(created_at.replace('Z', '+00:00'))
            except (ValueError, AttributeError):
                created_at = None
        
        # Parse extracted_at (saved_at in database) timestamp
        extracted_at = msg.get("saved_at")
        if extracted_at and isinstance(extracted_at, str):
            try:
                extracted_at = dt.fromisoformat(extracted_at.replace('Z', '+00:00'))
            except (ValueError, AttributeError):
                extracted_at = None
        
        message_schemas.append(TelegramMessageSchema(
            message_id=msg.get("message_id", 0),
            channel_username=None,  # Database doesn't have this field yet
            content=msg.get("content"),
            content_type=msg.get("content_type", "text"),
            media_urls=media_urls if isinstance(media_urls, list) else [],
            hashtags=[],  # TODO: Get from telegram_hashtags table
            mentions=[],  # TODO: Get from separate table
            created_at=created_at,
            extracted_at=extracted_at,
            metadata={},  # Can be populated with other fields if needed
        ))
    
    has_more = len(messages) > limit
    total = db.count_telegram_messages()  # Get actual count from database for pagination
    
    return PaginatedResponse(
        items=message_schemas,
        total=total,
        limit=limit,
        offset=offset,
        next_cursor=None,
        has_more=has_more,
    )


@router.get(
    "/messages/{message_id}",
    response_model=TelegramMessageSchema,
    summary="Get specific message details",
    description="""
    Retrieve detailed information about a specific Telegram message.
    """,
)
async def get_message(
    message_id: int,
    db: SocialMediaDatabase = Depends(get_db),
    user: Optional[dict] = Depends(get_optional_auth),
) -> TelegramMessageSchema:
    """
    Get specific Telegram message by ID.
    
    Args:
        message_id: Telegram message ID.
        db: Database instance (injected dependency).
        user: Optional authenticated user info.
        
    Returns:
        TelegramMessageSchema with message details.
        
    Raises:
        HTTPException: 404 if message not found.
        
    Example:
        GET /api/v1/telegram/messages/12345
        
        Response:
        {
            "message_id": 12345,
            "channel_username": "cooking_channel",
            "content": "Delicious pasta recipe!",
            ...
        }
    """
    from datetime import datetime as dt
    import json
    
    # Retrieve message from database
    message = db.get_telegram_message(message_id)
    
    if not message:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Message with ID {message_id} not found",
        )
    
    # Parse media_urls from JSON string if needed
    media_urls = message.get("media_urls", [])
    if isinstance(media_urls, str):
        try:
            media_urls = json.loads(media_urls) if media_urls else []
        except json.JSONDecodeError:
            media_urls = []
    
    # Parse created_at timestamp
    created_at = message.get("created_at")
    if created_at and isinstance(created_at, str):
        try:
            created_at = dt.fromisoformat(created_at.replace('Z', '+00:00'))
        except (ValueError, AttributeError):
            created_at = None
    
    # Parse extracted_at (saved_at in database) timestamp
    extracted_at = message.get("saved_at")
    if extracted_at and isinstance(extracted_at, str):
        try:
            extracted_at = dt.fromisoformat(extracted_at.replace('Z', '+00:00'))
        except (ValueError, AttributeError):
            extracted_at = None
    
    # Fetch hashtags from telegram_hashtags table
    # TODO: Implement hashtag retrieval from database
    hashtags = []
    
    return TelegramMessageSchema(
        message_id=message.get("message_id", 0),
        channel_username=None,  # Database doesn't have this field yet
        content=message.get("content"),
        content_type=message.get("content_type", "text"),
        media_urls=media_urls if isinstance(media_urls, list) else [],
        hashtags=hashtags,
        mentions=[],  # TODO: Get from separate table
        created_at=created_at,
        extracted_at=extracted_at,
        metadata={},
    )


@router.websocket("/ws/progress/{job_id}")
async def websocket_progress(
    websocket: WebSocket,
    job_id: str,
    ws_manager: WebSocketManager = Depends(get_websocket_manager),
    job_manager: JobManager = Depends(get_job_manager),
):
    """
    WebSocket endpoint for real-time job progress updates.
    
    Clients can connect to this endpoint to receive live progress updates
    for a specific extraction job. The connection will receive JSON messages
    with job status, progress percentage, and messages processed.
    
    Args:
        websocket: WebSocket connection.
        job_id: Unique job identifier.
        ws_manager: WebSocket manager (injected dependency).
        job_manager: Job state manager (injected dependency).
        
    Example:
        const ws = new WebSocket('ws://localhost:8000/api/v1/telegram/ws/progress/550e8400-e29b-41d4-a716-446655440000');
        
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

