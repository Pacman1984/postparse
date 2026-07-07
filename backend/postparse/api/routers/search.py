"""
FastAPI router for search endpoints.

This module provides HTTP endpoints for searching Instagram posts and
Telegram messages with various filters and cursor-based pagination.
"""

from datetime import datetime as dt
from typing import Dict, Any, List, Optional
from fastapi import APIRouter, Depends, HTTPException, Query, status, Response

from backend.postparse.core.data.database import SocialMediaDatabase
from backend.postparse.api.dependencies import get_db, get_optional_auth, get_cache_manager
from backend.postparse.api.services.cache_manager import CacheManager
from backend.postparse.api.schemas import (
    SearchPostsRequest,
    SearchMessagesRequest,
    SearchResponse,
    PostSearchResult,
    MessageSearchResult,
    PaginationMetadata,
)
import logging

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/api/v1/search",
    tags=["search"],
    responses={
        400: {"description": "Invalid request"},
        401: {"description": "Unauthorized"},
        500: {"description": "Internal server error"},
    },
)


@router.get(
    "/posts",
    response_model=SearchResponse[PostSearchResult],
    summary="Search Instagram posts",
    description="""
    Search Instagram posts with advanced filters and cursor-based pagination.
    
    Supports:
    - Multiple hashtags with OR logic (matches any hashtag)
    - Date range filtering
    - Content type filtering (image, video)
    - Owner username filtering
    - Cursor-based pagination for efficient navigation
    - Redis caching for improved performance
    
    Returns paginated search results with filter metadata and cache status headers.
    """,
)
async def search_posts(
    response: Response,
    request: SearchPostsRequest = Depends(),
    db: SocialMediaDatabase = Depends(get_db),
    cache: CacheManager = Depends(get_cache_manager),
    user: Dict[str, Any] = Depends(get_optional_auth),
) -> SearchResponse[PostSearchResult]:
    """
    Search Instagram posts with advanced filters and cursor-based pagination.
    
    This endpoint supports combined filtering with multiple criteria:
    - Hashtags: OR logic (matches posts with any of the specified hashtags)
    - Date range: Filters posts created within the specified time window
    - Content type: Filters by media type (video or image)
    - Owner username: Filters posts by owner
    
    Implements cursor-based pagination for efficient large result set traversal.
    Results are cached with Redis for improved performance on repeated queries.
    
    Args:
        response: FastAPI Response object for setting headers.
        request: SearchPostsRequest containing all query parameters.
        db: Database instance (injected dependency).
        cache: CacheManager for caching results.
        user: Optional authenticated user info.
        
    Returns:
        SearchResponse with filtered posts and metadata.
        
    Example:
        GET /api/v1/search/posts?hashtags=recipe&hashtags=cooking&content_type=video&limit=20
        
        Response:
        {
            "results": [...],
            "total_count": 150,
            "filters_applied": {
                "hashtags": ["recipe", "cooking"],
                "content_type": "video"
            },
            "pagination": {
                "cursor": null,
                "next_cursor": "MjAyNC0wMS0xNVQxMDozMDowMHwxMjM=",
                "has_more": true,
                "limit": 20
            }
        }
    """
    # Build filter parameters for database query
    date_range_tuple = None
    if request.date_range:
        date_range_tuple = (request.date_range.start_date, request.date_range.end_date)
    
    content_type_str = request.content_type.value if request.content_type else None
    
    # Generate cache key from filters
    cache_key = cache.generate_cache_key(
        "search:posts",
        hashtags=request.hashtags,
        date_range=date_range_tuple,
        content_type=content_type_str,
        owner_username=request.owner_username,
        limit=request.limit,
        cursor=request.cursor
    )
    
    # Check cache first
    cached_result = None
    if cache.is_available():
        cached_result = cache.get(cache_key)
        if cached_result:
            logger.debug(f"Cache hit for key: {cache_key}")
            response.headers["X-Cache-Status"] = "HIT"
            return SearchResponse(**cached_result)
    
    # Cache miss - query database
    logger.debug(f"Cache miss for key: {cache_key}")
    response.headers["X-Cache-Status"] = "MISS"
    
    # Validate cursor if provided
    if request.cursor:
        try:
            db._decode_cursor(request.cursor)
        except ValueError as e:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Invalid cursor: {str(e)}"
            )
    
    # Search database with all filters
    posts, next_cursor = db.search_instagram_posts(
        hashtags=request.hashtags,
        date_range=date_range_tuple,
        content_type=content_type_str,
        owner_username=request.owner_username,
        limit=request.limit,
        cursor=request.cursor
    )
    
    # Convert to search result schemas
    results = []
    for post in posts:
        # Parse created_at timestamp
        created_at = post.get("created_at")
        if isinstance(created_at, str) and created_at.strip():
            try:
                created_at = dt.fromisoformat(created_at.replace('Z', '+00:00'))
            except (ValueError, AttributeError):
                created_at = None
        else:
            created_at = None
        
        results.append(PostSearchResult(
            shortcode=post.get("shortcode", ""),
            owner_username=post.get("owner_username", ""),
            caption=post.get("caption", "")[:200] if post.get("caption") else None,
            is_video=post.get("is_video", False),
            likes=post.get("likes", 0),
            hashtags=post.get("hashtags", []),
            created_at=created_at,
        ))
    
    # Build filters_applied dict
    filters_applied = {}
    if request.hashtags:
        filters_applied["hashtags"] = request.hashtags
    if request.date_range:
        filters_applied["date_range"] = {
            "start_date": request.date_range.start_date.isoformat(),
            "end_date": request.date_range.end_date.isoformat()
        }
    if request.content_type:
        filters_applied["content_type"] = request.content_type.value
    if request.owner_username:
        filters_applied["owner_username"] = request.owner_username
    
    # Get total count with filters
    total_count = db.count_instagram_posts_filtered(
        hashtags=request.hashtags,
        date_range=date_range_tuple,
        content_type=content_type_str,
        owner_username=request.owner_username
    )
    
    # Build response
    response_data = SearchResponse(
        results=results,
        total_count=total_count,
        filters_applied=filters_applied,
        pagination=PaginationMetadata(
            cursor=request.cursor,
            next_cursor=next_cursor,
            has_more=next_cursor is not None,
            limit=request.limit
        ),
    )
    
    # Cache the result
    if cache.is_available():
        search_ttl = cache.config.get("api.cache.search_ttl", default=600)
        cache.set(cache_key, response_data.model_dump(), ttl=search_ttl)
    
    return response_data


@router.get(
    "/messages",
    response_model=SearchResponse[MessageSearchResult],
    summary="Search Telegram messages",
    description="""
    Search Telegram messages with advanced filters and cursor-based pagination.
    
    Supports:
    - Multiple hashtags with OR logic (matches any hashtag)
    - Date range filtering
    - Content type filtering (text, photo, video, document)
    - Cursor-based pagination for efficient navigation
    - Redis caching for improved performance
    
    Note: Channel username filtering is NOT supported as the underlying database
    schema does not store channel username information. Requests with channel_username
    will be rejected with a 400 error. Results include chat_id (numeric identifier)
    which can be used to identify the source chat/channel.
    
    Returns paginated search results with filter metadata and cache status headers.
    """,
)
async def search_messages(
    response: Response,
    request: SearchMessagesRequest = Depends(),
    db: SocialMediaDatabase = Depends(get_db),
    cache: CacheManager = Depends(get_cache_manager),
    user: Dict[str, Any] = Depends(get_optional_auth),
) -> SearchResponse[MessageSearchResult]:
    """
    Search Telegram messages with advanced filters and cursor-based pagination.
    
    This endpoint supports combined filtering with multiple criteria:
    - Hashtags: OR logic (matches messages with any of the specified hashtags)
    - Date range: Filters messages created within the specified time window
    - Content type: Filters by content type (text/photo/video/document)
    
    Note: Channel username filtering is NOT supported as the underlying database
    schema does not store channel username information. Results include chat_id
    (numeric identifier) which can be used to identify the source chat/channel.
    
    Implements cursor-based pagination for efficient large result set traversal.
    Results are cached with Redis for improved performance on repeated queries.
    
    Args:
        response: FastAPI Response object for setting headers.
        request: SearchMessagesRequest containing all query parameters.
        db: Database instance (injected dependency).
        cache: CacheManager for caching results.
        user: Optional authenticated user info.
        
    Returns:
        SearchResponse with filtered messages and metadata.
        Each message result includes chat_id for identifying the source.
        
    Raises:
        HTTPException: 400 if channel_username filter is provided (unsupported).
        
    Example:
        GET /api/v1/search/messages?hashtags=news&content_type=photo&limit=20
        
        Response:
        {
            "results": [
                {
                    "message_id": 12345,
                    "chat_id": -1001234567890,
                    "content": "News article...",
                    "content_type": "photo",
                    "hashtags": ["news"],
                    "created_at": "2024-01-15T10:30:00Z"
                }
            ],
            "total_count": 89,
            "filters_applied": {
                "hashtags": ["news"],
                "content_type": "photo"
            },
            "pagination": {
                "cursor": null,
                "next_cursor": "MjAyNC0wMS0xNVQxMDozMDowMHw0NTY=",
                "has_more": true,
                "limit": 20
            }
        }
    """
    # Validate that unsupported filters are not provided
    if request.channel_username:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="channel_username filter is not supported. The database does not store channel information for Telegram messages."
        )
    
    # Build filter parameters for database query
    date_range_tuple = None
    if request.date_range:
        date_range_tuple = (request.date_range.start_date, request.date_range.end_date)
    
    content_type_str = request.content_type.value if request.content_type else None
    
    # Generate cache key from filters
    cache_key = cache.generate_cache_key(
        "search:messages",
        hashtags=request.hashtags,
        date_range=date_range_tuple,
        content_type=content_type_str,
        limit=request.limit,
        cursor=request.cursor
    )
    
    # Check cache first
    cached_result = None
    if cache.is_available():
        cached_result = cache.get(cache_key)
        if cached_result:
            logger.debug(f"Cache hit for key: {cache_key}")
            response.headers["X-Cache-Status"] = "HIT"
            return SearchResponse(**cached_result)
    
    # Cache miss - query database
    logger.debug(f"Cache miss for key: {cache_key}")
    response.headers["X-Cache-Status"] = "MISS"
    
    # Validate cursor if provided
    if request.cursor:
        try:
            db._decode_cursor(request.cursor)
        except ValueError as e:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Invalid cursor: {str(e)}"
            )
    
    # Search database with all filters
    messages, next_cursor = db.search_telegram_messages(
        hashtags=request.hashtags,
        date_range=date_range_tuple,
        content_type=content_type_str,
        limit=request.limit,
        cursor=request.cursor
    )
    
    # Convert to search result schemas
    results = []
    for msg in messages:
        # Parse created_at timestamp
        created_at = msg.get("created_at")
        if isinstance(created_at, str) and created_at.strip():
            try:
                created_at = dt.fromisoformat(created_at.replace('Z', '+00:00'))
            except (ValueError, AttributeError):
                created_at = None
        else:
            created_at = None
        
        results.append(MessageSearchResult(
            message_id=msg.get("message_id", 0),
            chat_id=msg.get("chat_id"),  # Telegram chat/channel ID
            channel_username=None,  # Not stored in database
            content=msg.get("content", "")[:200] if msg.get("content") else None,
            content_type=msg.get("content_type", "text"),
            hashtags=msg.get("hashtags", []),
            created_at=created_at,
        ))
    
    # Build filters_applied dict
    filters_applied = {}
    if request.hashtags:
        filters_applied["hashtags"] = request.hashtags
    if request.date_range:
        filters_applied["date_range"] = {
            "start_date": request.date_range.start_date.isoformat(),
            "end_date": request.date_range.end_date.isoformat()
        }
    if request.content_type:
        filters_applied["content_type"] = request.content_type.value
    
    # Get total count with filters
    total_count = db.count_telegram_messages_filtered(
        hashtags=request.hashtags,
        date_range=date_range_tuple,
        content_type=content_type_str
    )
    
    # Build response
    response_data = SearchResponse(
        results=results,
        total_count=total_count,
        filters_applied=filters_applied,
        pagination=PaginationMetadata(
            cursor=request.cursor,
            next_cursor=next_cursor,
            has_more=next_cursor is not None,
            limit=request.limit
        ),
    )
    
    # Cache the result
    if cache.is_available():
        search_ttl = cache.config.get("api.cache.search_ttl", default=600)
        cache.set(cache_key, response_data.model_dump(), ttl=search_ttl)
    
    return response_data


@router.get(
    "/hashtags",
    response_model=Dict[str, List[Dict[str, Any]]],
    summary="List all unique hashtags",
    description="""
    List all unique hashtags with usage counts.
    
    Returns hashtags from both Instagram posts and Telegram messages,
    aggregated and sorted by usage count (descending).
    """,
)
async def list_hashtags(
    limit: int = Query(default=100, ge=1, le=500, description="Maximum hashtags to return"),
    db: SocialMediaDatabase = Depends(get_db),
    user: Dict[str, Any] = Depends(get_optional_auth),
) -> Dict[str, List[Dict[str, Any]]]:
    """
    List all unique hashtags with usage counts from database.
    
    Aggregates hashtags from both Instagram posts and Telegram messages,
    counts their occurrences, and returns them sorted by count (descending).
    
    Args:
        limit: Maximum number of hashtags to return.
        db: Database instance (injected dependency).
        user: Optional authenticated user info.
        
    Returns:
        Dictionary with hashtags and their usage counts.
        
    Example:
        GET /api/v1/search/hashtags?limit=50
        
        Response:
        {
            "hashtags": [
                {"tag": "recipe", "count": 125, "source": "both"},
                {"tag": "cooking", "count": 89, "source": "instagram"},
                {"tag": "italian", "count": 67, "source": "telegram"}
            ]
        }
    """
    # Use database method to get all hashtags (handles connection internally)
    hashtags = db.get_all_hashtags(limit=limit)
    return {"hashtags": hashtags}

