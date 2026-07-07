"""
Pydantic schemas for Instagram extraction endpoints.

This module defines request/response models for Instagram post extraction,
compatible with the database schema and parser implementations.
"""

from datetime import datetime
from typing import List, Optional, Dict, Any
from pydantic import BaseModel, Field, ConfigDict, HttpUrl, SecretStr

from .telegram import ExtractionStatus, JobStatusResponse


class InstagramExtractRequest(BaseModel):
    """
    Request schema for triggering Instagram post extraction.

    Supports both Instaloader (scraping) and Platform API methods.

    Attributes:
        username: Instagram account username.
        password: Account password (for Instaloader method).
        access_token: API access token (for Platform API method).
        limit: Maximum number of posts to extract.
        force_update: Whether to re-extract already processed posts.
        use_api: Use Platform API instead of Instaloader.

    Example:
        # Instaloader method
        {
            "username": "cooking_profile",
            "password": "secret123",
            "limit": 50,
            "force_update": false,
            "use_api": false
        }

        # Platform API method
        {
            "username": "cooking_profile",
            "access_token": "EAABsbCS1iHgBO...",
            "limit": 50,
            "force_update": false,
            "use_api": true
        }
    """

    model_config = ConfigDict(json_schema_extra={
        "examples": [
            {
                "username": "cooking_profile",
                "password": "secret123",
                "limit": 50,
                "force_update": False,
                "use_api": False
            },
            {
                "username": "cooking_profile",
                "access_token": "EAABsbCS1iHgBO...",
                "limit": 50,
                "force_update": False,
                "use_api": True
            }
        ]
    })

    username: str = Field(
        ...,
        min_length=1,
        max_length=30,
        pattern=r"^[a-zA-Z0-9._]+$",
        description="Instagram username",
        examples=["cooking_profile"]
    )
    password: Optional[SecretStr] = Field(
        default=None,
        description="Account password (for Instaloader method)"
    )
    access_token: Optional[SecretStr] = Field(
        default=None,
        description="API access token (for Platform API method)"
    )
    limit: Optional[int] = Field(
        default=50,
        ge=1,
        le=1000,
        description="Maximum posts to extract"
    )
    force_update: bool = Field(
        default=False,
        description="Re-extract already processed posts"
    )
    use_api: bool = Field(
        default=False,
        description="Use Platform API instead of Instaloader"
    )


class InstagramExtractResponse(BaseModel):
    """
    Response schema for Instagram extraction job initiation.

    Attributes:
        job_id: Unique identifier for tracking the extraction job.
        status: Current job status.
        post_count: Estimated number of posts to process.
        estimated_time: Estimated completion time in seconds.

    Example:
        {
            "job_id": "550e8400-e29b-41d4-a716-446655440000",
            "status": "pending",
            "post_count": 0,
            "estimated_time": 30
        }
    """

    model_config = ConfigDict(json_schema_extra={
        "examples": [
            {
                "job_id": "550e8400-e29b-41d4-a716-446655440000",
                "status": "pending",
                "post_count": 0,
                "estimated_time": 30
            }
        ]
    })

    job_id: str = Field(
        ...,
        description="Unique job identifier",
        examples=["550e8400-e29b-41d4-a716-446655440000"]
    )
    status: ExtractionStatus = Field(
        ...,
        description="Current job status"
    )
    post_count: int = Field(
        default=0,
        ge=0,
        description="Estimated posts to process"
    )
    estimated_time: Optional[int] = Field(
        default=None,
        ge=0,
        description="Estimated completion time (seconds)"
    )


class InstagramPostSchema(BaseModel):
    """
    Schema representing a single Instagram post.

    Matches the database schema for instagram_posts table.

    Attributes:
        shortcode: Instagram post shortcode (unique identifier).
        owner_username: Username of post owner.
        caption: Post caption text.
        is_video: Whether the post contains video.
        media_url: URL to post media.
        likes: Number of likes.
        comments: Number of comments.
        hashtags: List of extracted hashtags (without #).
        mentions: List of mentioned usernames (without @).
        created_at: Post creation timestamp.
        extracted_at: When the post was extracted.
        metadata: Additional post metadata.

    Example:
        {
            "shortcode": "CX1a2b3c4d5",
            "owner_username": "cooking_profile",
            "caption": "Homemade pizza! #italian #pizza #cooking",
            "is_video": false,
            "media_url": "https://instagram.com/.../photo.jpg",
            "likes": 1250,
            "comments": 48,
            "hashtags": ["italian", "pizza", "cooking"],
            "mentions": ["chef_friend"],
            "created_at": "2025-11-19T10:00:00Z",
            "extracted_at": "2025-11-19T10:30:00Z",
            "metadata": {}
        }
    """

    model_config = ConfigDict(
        from_attributes=True,
        json_schema_extra={
            "examples": [
                {
                    "shortcode": "CX1a2b3c4d5",
                    "owner_username": "cooking_profile",
                    "caption": "Homemade pizza! #italian #pizza #cooking",
                    "is_video": False,
                    "media_url": "https://instagram.com/.../photo.jpg",
                    "likes": 1250,
                    "comments": 48,
                    "hashtags": ["italian", "pizza", "cooking"],
                    "mentions": ["chef_friend"],
                    "created_at": "2025-11-19T10:00:00Z",
                    "extracted_at": "2025-11-19T10:30:00Z",
                    "metadata": {}
                }
            ]
        }
    )

    shortcode: str = Field(
        ...,
        description="Instagram post shortcode"
    )
    owner_username: Optional[str] = Field(
        default=None,
        description="Post owner username"
    )
    caption: Optional[str] = Field(
        default=None,
        description="Post caption text"
    )
    is_video: bool = Field(
        default=False,
        description="Whether post contains video"
    )
    media_url: Optional[str] = Field(
        default=None,
        description="URL to post media"
    )
    likes: int = Field(
        default=0,
        ge=0,
        description="Number of likes"
    )
    comments: int = Field(
        default=0,
        ge=0,
        description="Number of comments"
    )
    hashtags: List[str] = Field(
        default_factory=list,
        description="Extracted hashtags (without #)"
    )
    mentions: List[str] = Field(
        default_factory=list,
        description="Mentioned usernames (without @)"
    )
    created_at: Optional[datetime] = Field(
        default=None,
        description="Post creation timestamp"
    )
    extracted_at: Optional[datetime] = Field(
        default=None,
        description="Extraction timestamp"
    )
    metadata: Dict[str, Any] = Field(
        default_factory=dict,
        description="Additional post metadata"
    )
