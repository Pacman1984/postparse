"""
FastAPI router for Instagram extraction endpoints.

This module provides HTTP endpoints for triggering Instagram post extraction,
checking job status, and retrieving extracted posts.

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
    get_instagram_extraction_service,
)
from backend.postparse.api.services.job_manager import JobManager
from backend.postparse.api.services.websocket_manager import WebSocketManager
from backend.postparse.api.services.extraction_service import InstagramExtractionService
from backend.postparse.api.schemas import (
    InstagramExtractRequest,
    InstagramExtractResponse,
    InstagramPostSchema,
    JobStatusResponse,
    ExtractionStatus,
    PaginatedResponse,
)

router = APIRouter(
    prefix="/api/v1/instagram",
    tags=["instagram"],
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
    response_model=InstagramExtractResponse,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Trigger Instagram post extraction",
    description="""
    Start an async extraction job for Instagram posts.
    
    This endpoint initiates a background job that will:
    1. Authenticate with Instagram (Instaloader or Platform API)
    2. Extract posts from the specified profile
    3. Parse and store posts in the database
    
    Returns a job_id for tracking extraction progress.
    
    Note: Actual extraction logic will be implemented in the next phase.
    """,
)
async def extract_posts(
    request: InstagramExtractRequest,
    background_tasks: BackgroundTasks,
    job_manager: JobManager = Depends(get_job_manager),
    extraction_service: InstagramExtractionService = Depends(get_instagram_extraction_service),
    user: Optional[dict] = Depends(get_optional_auth),
) -> InstagramExtractResponse:
    """
    Trigger Instagram post extraction with background processing.
    
    Args:
        request: Extraction request with Instagram credentials and options.
        background_tasks: FastAPI background tasks manager.
        job_manager: Job state manager (injected dependency).
        extraction_service: Extraction service (injected dependency).
        user: Optional authenticated user info.
        
    Returns:
        InstagramExtractResponse with job_id for tracking.
        
    Raises:
        HTTPException: 400 if credentials are missing for selected method.
        
    Example:
        POST /api/v1/instagram/extract
        {
            "username": "cooking_profile",
            "password": "secret123",
            "limit": 50,
            "use_api": false
        }
        
        Response:
        {
            "job_id": "550e8400-e29b-41d4-a716-446655440000",
            "status": "pending",
            "post_count": 0,
            "estimated_time": 30
        }
    """
    # Validate credentials based on use_api flag
    if request.use_api:
        if not request.access_token:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Access token is required when use_api=true",
            )
        # Instagram API-based extraction is not yet implemented
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Instagram API-based extraction (use_api=true) is not yet supported; use use_api=false for Instaloader-based extraction.",
        )
    else:
        if not request.password:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Password is required when use_api=false",
            )
    
    # Create job in job manager
    job_id = job_manager.create_job('instagram', request.model_dump())
    
    # Add extraction task to background tasks
    # BackgroundTasks supports async functions, so we can add the async method directly
    background_tasks.add_task(
        extraction_service.run_extraction,
        job_id=job_id,
        username=request.username,
        password=request.password.get_secret_value() if request.password else None,
        access_token=request.access_token.get_secret_value() if request.access_token else None,
        limit=request.limit,
        force_update=request.force_update,
        use_api=request.use_api,
    )
    
    return InstagramExtractResponse(
        job_id=job_id,
        status=ExtractionStatus.PENDING,
        post_count=0,
        estimated_time=30,
    )


@router.get(
    "/jobs/{job_id}",
    response_model=JobStatusResponse,
    summary="Check extraction job status",
    description="""
    Query the status of an Instagram extraction job.
    
    Returns current progress, posts processed, and any errors encountered.
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
        job_id: Unique job identifier from extract_posts.
        job_manager: Job state manager (injected dependency).
        user: Optional authenticated user info.
        
    Returns:
        JobStatusResponse with current job status and progress.
        
    Raises:
        HTTPException: 404 if job not found.
        
    Example:
        GET /api/v1/instagram/jobs/550e8400-e29b-41d4-a716-446655440000
        
        Response:
        {
            "job_id": "550e8400-e29b-41d4-a716-446655440000",
            "status": "running",
            "progress": 65,
            "messages_processed": 32,
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
    "/posts",
    response_model=PaginatedResponse[InstagramPostSchema],
    summary="List extracted Instagram posts",
    description="""
    Retrieve extracted Instagram posts with pagination.
    
    Currently supports basic pagination via limit parameter.
    
    Note: Advanced filtering (owner_username, offset, hashtags, date range) 
    is planned for a future phase and is not yet implemented.
    """,
)
async def get_posts(
    limit: int = Query(default=50, ge=1, le=100, description="Maximum results to return"),
    offset: int = Query(default=0, ge=0, description="Number of results to skip (not yet implemented)"),
    owner_username: Optional[str] = Query(default=None, description="Filter by owner (not yet implemented)"),
    db: SocialMediaDatabase = Depends(get_db),
    user: Optional[dict] = Depends(get_optional_auth),
) -> PaginatedResponse[InstagramPostSchema]:
    """
    List extracted Instagram posts with pagination.
    
    Currently returns posts ordered by creation date (newest first) with basic limit-based pagination.
    The offset and owner_username parameters are accepted but not yet implemented.
    
    Args:
        limit: Maximum number of posts to return.
        offset: Number of posts to skip (accepted but not yet implemented).
        owner_username: Optional username filter (accepted but not yet implemented).
        db: Database instance (injected dependency).
        user: Optional authenticated user info.
        
    Returns:
        PaginatedResponse with list of posts and pagination metadata.
        
    Example:
        GET /api/v1/instagram/posts?limit=20
        
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
    # Use database method to retrieve posts
    # Note: offset and owner_username filters are not yet implemented
    from datetime import datetime as dt
    
    posts = db.get_instagram_posts(limit=limit + 1)  # Get one extra to check if more exist
    
    # Convert to schema objects
    post_schemas = []
    for post in posts[:limit]:
        # Parse created_at timestamp
        created_at = post.get("created_at")
        if created_at and isinstance(created_at, str):
            try:
                created_at = dt.fromisoformat(created_at.replace('Z', '+00:00'))
            except (ValueError, AttributeError):
                created_at = None
        
        # Parse extracted_at (fetched_at in database) timestamp
        extracted_at = post.get("fetched_at")
        if extracted_at and isinstance(extracted_at, str):
            try:
                extracted_at = dt.fromisoformat(extracted_at.replace('Z', '+00:00'))
            except (ValueError, AttributeError):
                extracted_at = None
        
        post_schemas.append(InstagramPostSchema(
            shortcode=post.get("shortcode", ""),
            owner_username=post.get("owner_username"),
            caption=post.get("caption"),
            is_video=bool(post.get("is_video", False)),
            media_url=post.get("media_url"),
            likes=max(0, post.get("likes") or 0),
            comments=max(0, post.get("comments") or 0),
            hashtags=[],  # TODO: Get from instagram_hashtags table
            mentions=[],  # TODO: Get from instagram_mentions table
            created_at=created_at,
            extracted_at=extracted_at,
            metadata={},  # Can be populated with other fields if needed
        ))
    
    has_more = len(posts) > limit
    total = db.count_instagram_posts()  # Get actual count from database for pagination
    
    return PaginatedResponse(
        items=post_schemas,
        total=total,
        limit=limit,
        offset=offset,
        next_cursor=None,
        has_more=has_more,
    )


@router.get(
    "/posts/{shortcode}",
    response_model=InstagramPostSchema,
    summary="Get specific post details",
    description="""
    Retrieve detailed information about a specific Instagram post.
    """,
)
async def get_post(
    shortcode: str,
    db: SocialMediaDatabase = Depends(get_db),
    user: Optional[dict] = Depends(get_optional_auth),
) -> InstagramPostSchema:
    """
    Get specific Instagram post by shortcode.
    
    Args:
        shortcode: Instagram post shortcode.
        db: Database instance (injected dependency).
        user: Optional authenticated user info.
        
    Returns:
        InstagramPostSchema with post details.
        
    Raises:
        HTTPException: 404 if post not found.
        
    Example:
        GET /api/v1/instagram/posts/CX1a2b3c4d5
        
        Response:
        {
            "shortcode": "CX1a2b3c4d5",
            "owner_username": "cooking_profile",
            "caption": "Homemade pizza!",
            ...
        }
    """
    from datetime import datetime as dt
    
    # Retrieve post from database
    post = db.get_instagram_post(shortcode)
    
    if not post:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Post with shortcode {shortcode} not found",
        )
    
    # Parse created_at timestamp
    created_at = post.get("created_at")
    if created_at and isinstance(created_at, str):
        try:
            created_at = dt.fromisoformat(created_at.replace('Z', '+00:00'))
        except (ValueError, AttributeError):
            created_at = None
    
    # Parse extracted_at (fetched_at in database) timestamp
    extracted_at = post.get("fetched_at")
    if extracted_at and isinstance(extracted_at, str):
        try:
            extracted_at = dt.fromisoformat(extracted_at.replace('Z', '+00:00'))
        except (ValueError, AttributeError):
            extracted_at = None
    
    # Fetch hashtags and mentions from respective tables
    # TODO: Implement hashtag and mention retrieval from database
    hashtags = []
    mentions = []
    
    return InstagramPostSchema(
        shortcode=post.get("shortcode", ""),
        owner_username=post.get("owner_username"),
        caption=post.get("caption"),
        is_video=post.get("is_video", False),
        media_url=post.get("media_url"),
        likes=max(0, post.get("likes") or 0),
        comments=max(0, post.get("comments") or 0),
        hashtags=hashtags,
        mentions=mentions,
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
    with job status, progress percentage, and posts processed.
    
    Args:
        websocket: WebSocket connection.
        job_id: Unique job identifier.
        ws_manager: WebSocket manager (injected dependency).
        job_manager: Job state manager (injected dependency).
        
    Example:
        const ws = new WebSocket('ws://localhost:8000/api/v1/instagram/ws/progress/550e8400-e29b-41d4-a716-446655440000');
        
        ws.onmessage = (event) => {
            const data = JSON.parse(event.data);
            console.log(`Progress: ${data.progress}%`);
        };
        
    Message Format:
        {
            "job_id": "550e8400-e29b-41d4-a716-446655440000",
            "status": "running",
            "progress": 65,
            "messages_processed": 32,
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



