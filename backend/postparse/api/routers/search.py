"""
FastAPI router for search endpoints.

This module provides HTTP endpoints for searching Instagram posts and
Telegram messages with various filters.

Note: Advanced filtering and cursor-based pagination will be implemented
in the next phase. This module contains basic implementations.
"""

from datetime import datetime as dt
from typing import Dict, Any, List
from fastapi import APIRouter, Depends, HTTPException, Query, status

from backend.postparse.core.data.database import SocialMediaDatabase
from backend.postparse.api.dependencies import get_db, get_optional_auth
from backend.postparse.api.schemas import (
    SearchPostsRequest,
    SearchMessagesRequest,
    SearchResponse,
    PostSearchResult,
    MessageSearchResult,
)

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
    Search Instagram posts with basic filters.
    
    Currently supports:
    - Basic hashtag filtering (single hashtag only; OR logic for multiple hashtags is planned)
    - Limit-based pagination
    
    Planned for future phases:
    - Multiple hashtags with OR logic
    - Date range filtering
    - Content type filtering (image, video)
    - Owner username filtering
    - Offset-based pagination
    
    Returns paginated search results with filter metadata.
    """,
)
async def search_posts(
    request: SearchPostsRequest = Depends(),
    db: SocialMediaDatabase = Depends(get_db),
    user: Dict[str, Any] = Depends(get_optional_auth),
) -> SearchResponse[PostSearchResult]:
    """
    Search Instagram posts with basic filters.
    
    Currently implements minimal filtering: if hashtags are provided, uses only the first hashtag.
    The owner_username and offset parameters are accepted but not yet implemented.
    Multiple hashtags with OR logic is planned for a future phase.
    
    Args:
        request: SearchPostsRequest containing all query parameters.
        db: Database instance (injected dependency).
        user: Optional authenticated user info.
        
    Returns:
        SearchResponse with filtered posts and metadata.
        
    Example:
        GET /api/v1/search/posts?hashtags=recipe&limit=20
        
        Response:
        {
            "results": [...],
            "total_count": 20,
            "filters_applied": {"hashtags": ["recipe"]},
            "pagination": {"limit": 20, "offset": 0, "next_offset": 20}
        }
    """
    filters_applied = {}
    
    # Apply hashtag filter (currently only first hashtag is used)
    # Note: OR logic for multiple hashtags, owner_username, and offset are not yet implemented
    # date_range and content_type are also not yet implemented but accepted in the schema
    if request.hashtags:
        filters_applied["hashtags"] = request.hashtags[:1]  # Only track first hashtag currently used
        # Get posts by hashtag (using first hashtag only)
        posts = db.get_posts_by_hashtag(request.hashtags[0], limit=request.limit + 1)
    else:
        # Get all posts (owner_username filter not yet implemented)
        # Note: owner_username is accepted in the schema but not yet applied
        posts = db.get_instagram_posts(limit=request.limit + 1)
    
    # Convert to search result schemas
    results = []
    for post in posts[:request.limit]:
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
            caption=post.get("caption", "")[:200] if post.get("caption") else None,  # Truncate
            is_video=post.get("is_video", False),
            likes=post.get("likes", 0),
            hashtags=post.get("hashtags", []),
            created_at=created_at,
        ))
    
    has_more = len(posts) > request.limit
    next_offset = request.offset + request.limit if has_more else None
    prev_offset = max(0, request.offset - request.limit) if request.offset > 0 else None
    
    # Get actual total count based on filters applied
    if request.hashtags:
        # When filtering by hashtag, count only posts with that hashtag
        total_count = db.count_instagram_posts_by_hashtag(request.hashtags[0])
    else:
        # When not filtering, count all posts
        total_count = db.count_instagram_posts()
    
    return SearchResponse(
        results=results,
        total_count=total_count,
        filters_applied=filters_applied,
        pagination={
            "limit": request.limit,
            "offset": request.offset,
            "next_offset": next_offset,
            "prev_offset": prev_offset,
        },
    )


@router.get(
    "/messages",
    response_model=SearchResponse[MessageSearchResult],
    summary="Search Telegram messages",
    description="""
    Search Telegram messages with basic filters.
    
    Currently supports:
    - Limit-based pagination
    
    Planned for future phases:
    - Hashtag filtering (OR logic)
    - Date range filtering
    - Content type filtering (text, photo, video, document)
    - Channel username filtering
    - Offset-based pagination
    
    Returns paginated search results with filter metadata.
    """,
)
async def search_messages(
    request: SearchMessagesRequest = Depends(),
    db: SocialMediaDatabase = Depends(get_db),
    user: Dict[str, Any] = Depends(get_optional_auth),
) -> SearchResponse[MessageSearchResult]:
    """
    Search Telegram messages with basic filters.
    
    Currently returns all messages ordered by creation date (newest first) with basic limit-based pagination.
    The hashtags, channel_username, and offset parameters are accepted but not yet implemented.
    
    Args:
        request: SearchMessagesRequest containing all query parameters.
        db: Database instance (injected dependency).
        user: Optional authenticated user info.
        
    Returns:
        SearchResponse with filtered messages and metadata.
        
    Example:
        GET /api/v1/search/messages?limit=50
        
        Response:
        {
            "results": [...],
            "total_count": 50,
            "filters_applied": {},
            "pagination": {"limit": 50, "offset": 0}
        }
    """
    filters_applied = {}
    
    # Note: hashtags, channel_username, and offset filters are not yet implemented
    # These parameters are accepted but currently ignored
    # date_range and content_type are also not yet implemented but accepted in the schema
    # Only add filters to filters_applied when they're actually being used
    
    # Get messages from database (no filtering applied yet)
    messages = db.get_telegram_messages(limit=request.limit + 1)
    
    # Convert to search result schemas
    results = []
    for msg in messages[:request.limit]:
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
            channel_username=msg.get("channel_username", ""),
            content=msg.get("content", "")[:200] if msg.get("content") else None,  # Truncate
            content_type=msg.get("content_type", "text"),
            hashtags=msg.get("hashtags", []),
            created_at=created_at,
        ))
    
    has_more = len(messages) > request.limit
    next_offset = request.offset + request.limit if has_more else None
    prev_offset = max(0, request.offset - request.limit) if request.offset > 0 else None
    
    # Get actual total count from database
    # Note: When hashtag/channel filtering is implemented, this will need to be conditional
    total_count = db.count_telegram_messages()
    
    return SearchResponse(
        results=results,
        total_count=total_count,
        filters_applied=filters_applied,
        pagination={
            "limit": request.limit,
            "offset": request.offset,
            "next_offset": next_offset,
            "prev_offset": prev_offset,
        },
    )


@router.get(
    "/hashtags",
    response_model=Dict[str, List[Dict[str, Any]]],
    summary="List all unique hashtags",
    description="""
    List all unique hashtags with usage counts.
    
    Returns hashtags from both Instagram posts and Telegram messages,
    sorted by usage count (descending).
    """,
)
async def list_hashtags(
    limit: int = Query(default=100, ge=1, le=500, description="Maximum hashtags to return"),
    db: SocialMediaDatabase = Depends(get_db),
    user: Dict[str, Any] = Depends(get_optional_auth),
) -> Dict[str, List[Dict[str, Any]]]:
    """
    List all unique hashtags with usage counts.
    
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
    # TODO: Implement actual hashtag aggregation from database
    # This is a placeholder that returns mock data
    
    return {
        "hashtags": [
            {"tag": "recipe", "count": 125, "source": "both"},
            {"tag": "cooking", "count": 89, "source": "instagram"},
            {"tag": "italian", "count": 67, "source": "telegram"},
            {"tag": "pasta", "count": 45, "source": "both"},
        ]
    }

