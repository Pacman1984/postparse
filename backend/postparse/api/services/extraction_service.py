"""
Extraction Service for orchestrating parser integrations with job tracking.

This module provides services that integrate parsers with job management and
WebSocket progress updates, handling the complete extraction lifecycle.
"""

import asyncio
import logging
import time
from typing import Optional

from backend.postparse.api.schemas.telegram import ExtractionStatus
from backend.postparse.api.services.job_manager import JobManager
from backend.postparse.api.services.websocket_manager import WebSocketManager
from backend.postparse.core.data.database import SocialMediaDatabase
from backend.postparse.services.parsers.instagram.instagram_parser import (
    InstagramAPIParser,
    InstaloaderParser,
)
from backend.postparse.services.parsers.telegram.telegram_parser import TelegramParser

logger = logging.getLogger(__name__)


class TelegramExtractionService:
    """
    Service for Telegram message extraction with job tracking.
    
    This service orchestrates TelegramParser with JobManager and WebSocketManager
    to provide real-time extraction with progress updates.
    
    Example:
        >>> service = TelegramExtractionService(job_manager, ws_manager, db)
        >>> await service.run_extraction(
        ...     job_id="...",
        ...     api_id=12345678,
        ...     api_hash="abc123",
        ...     phone="+1234567890",
        ...     limit=100
        ... )
    """
    
    def __init__(
        self,
        job_manager: JobManager,
        ws_manager: WebSocketManager,
        db: SocialMediaDatabase,
    ):
        """
        Initialize TelegramExtractionService.
        
        Args:
            job_manager: JobManager instance for job tracking
            ws_manager: WebSocketManager instance for progress updates
            db: SocialMediaDatabase instance for data storage
        """
        self.job_manager = job_manager
        self.ws_manager = ws_manager
        self.db = db
    
    async def run_extraction(
        self,
        job_id: str,
        api_id: int,
        api_hash: str,
        phone: Optional[str],
        limit: Optional[int],
        force_update: bool,
        max_requests_per_session: Optional[int],
    ) -> None:
        """
        Execute Telegram message extraction with progress tracking.
        
        This method runs the complete extraction lifecycle:
        1. Mark job as RUNNING
        2. Connect to Telegram via TelegramParser
        3. Fetch messages in batches
        4. Update progress and broadcast via WebSocket
        5. Save messages to database
        6. Mark job as COMPLETED or FAILED
        
        Args:
            job_id: UUID of the extraction job
            api_id: Telegram API ID
            api_hash: Telegram API hash
            phone: Phone number (optional if session exists)
            limit: Maximum messages to fetch
            force_update: Whether to force re-fetch existing messages
            max_requests_per_session: Rate limiting parameter
        
        Example:
            >>> await service.run_extraction(
            ...     job_id="550e8400-e29b-41d4-a716-446655440000",
            ...     api_id=12345678,
            ...     api_hash="0123456789abcdef",
            ...     phone="+1234567890",
            ...     limit=100,
            ...     force_update=False,
            ...     max_requests_per_session=30
            ... )
        """
        try:
            # Mark job as running
            self.job_manager.update_job_status(
                job_id, ExtractionStatus.RUNNING, 0, 0, []
            )
            await self.ws_manager.broadcast_progress(
                job_id,
                {
                    "job_id": job_id,
                    "status": "running",
                    "progress": 0,
                    "messages_processed": 0,
                    "errors": [],
                },
            )
            
            logger.info(f"Starting Telegram extraction for job {job_id}")
            
            # Create parser with non-interactive mode
            parser = TelegramParser(
                api_id=api_id,
                api_hash=api_hash,
                phone=phone,
                session_file=f"telegram_session_{api_id}",
                interactive=False,  # Non-interactive for API usage
            )
            
            messages_processed = 0
            last_broadcast_time = time.time()
            broadcast_interval = 5.0  # seconds
            
            # Use async context manager
            async with parser:
                logger.info(f"Connected to Telegram for job {job_id}")
                
                # Iterate over messages generator
                async for message_data in parser.get_saved_messages(
                    limit=limit,
                    max_requests_per_session=max_requests_per_session,
                    db=self.db,
                    force_update=force_update
                ):
                    try:
                        # Save message to database
                        await asyncio.to_thread(
                            self.db._insert_telegram_message,
                            message_id=message_data["message_id"],
                            chat_id=message_data.get("chat_id"),
                            content=message_data.get("content"),
                            content_type=message_data.get("content_type", "text"),
                            media_urls=message_data.get("media_urls"),
                            views=message_data.get("views"),
                            forwards=message_data.get("forwards"),
                            reply_to_msg_id=message_data.get("reply_to_msg_id"),
                            created_at=message_data.get("created_at"),
                            hashtags=message_data.get("hashtags")
                        )
                        messages_processed += 1
                        
                        # Calculate progress
                        progress = self._calculate_progress(messages_processed, limit)
                        
                        # Update job status
                        self.job_manager.update_job_status(
                            job_id,
                            ExtractionStatus.RUNNING,
                            progress,
                            messages_processed,
                            [],
                        )
                        
                        # Broadcast progress every N messages or every X seconds
                        current_time = time.time()
                        if (
                            messages_processed % 10 == 0
                            or current_time - last_broadcast_time >= broadcast_interval
                        ):
                            await self.ws_manager.broadcast_progress(
                                job_id,
                                {
                                    "job_id": job_id,
                                    "status": "running",
                                    "progress": progress,
                                    "messages_processed": messages_processed,
                                    "errors": [],
                                },
                            )
                            last_broadcast_time = current_time
                        
                    except Exception as e:
                        logger.error(
                            f"Error saving message in job {job_id}: {e}",
                            exc_info=True,
                        )
                        # Continue processing other messages
                        continue
            
            # Mark as completed
            self.job_manager.mark_job_completed(job_id, messages_processed)
            await self.ws_manager.broadcast_progress(
                job_id,
                {
                    "job_id": job_id,
                    "status": "completed",
                    "progress": 100,
                    "messages_processed": messages_processed,
                    "errors": [],
                },
            )
            
            logger.info(
                f"Telegram extraction completed for job {job_id}: "
                f"{messages_processed} messages"
            )
            
        except ValueError as e:
            # Handle authentication/session errors
            error_msg = f"Authentication error: {str(e)}"
            logger.error(f"Job {job_id} failed: {error_msg}")
            self.job_manager.mark_job_failed(job_id, error_msg)
            await self.ws_manager.broadcast_progress(
                job_id,
                {
                    "job_id": job_id,
                    "status": "failed",
                    "progress": self.job_manager.get_job(job_id).progress,
                    "messages_processed": self.job_manager.get_job(job_id).messages_processed,
                    "errors": [error_msg],
                },
            )
            
        except Exception as e:
            # Handle all other errors
            error_msg = f"Extraction error: {str(e)}"
            logger.error(f"Job {job_id} failed: {error_msg}", exc_info=True)
            self.job_manager.mark_job_failed(job_id, error_msg)
            await self.ws_manager.broadcast_progress(
                job_id,
                {
                    "job_id": job_id,
                    "status": "failed",
                    "progress": self.job_manager.get_job(job_id).progress,
                    "messages_processed": self.job_manager.get_job(job_id).messages_processed,
                    "errors": [error_msg],
                },
            )
    
    def _calculate_progress(self, current: int, total: Optional[int]) -> int:
        """
        Calculate progress percentage.
        
        Args:
            current: Number of items processed
            total: Total number of items (None if unknown)
        
        Returns:
            Progress percentage (0-100)
        """
        if total is None or total == 0:
            # Unknown total, use logarithmic scale for progress
            return min(95, int(50 + 10 * (current / 100)))
        return min(100, int((current / total) * 100))


class InstagramExtractionService:
    """
    Service for Instagram post extraction with job tracking.
    
    This service orchestrates InstaloaderParser/InstagramAPIParser with JobManager
    and WebSocketManager to provide real-time extraction with progress updates.
    
    Example:
        >>> service = InstagramExtractionService(job_manager, ws_manager, db)
        >>> await service.run_extraction(
        ...     job_id="...",
        ...     username="cooking_profile",
        ...     password="secret",
        ...     limit=50,
        ...     use_api=False
        ... )
    """
    
    def __init__(
        self,
        job_manager: JobManager,
        ws_manager: WebSocketManager,
        db: SocialMediaDatabase,
    ):
        """
        Initialize InstagramExtractionService.
        
        Args:
            job_manager: JobManager instance for job tracking
            ws_manager: WebSocketManager instance for progress updates
            db: SocialMediaDatabase instance for data storage
        """
        self.job_manager = job_manager
        self.ws_manager = ws_manager
        self.db = db
    
    async def run_extraction(
        self,
        job_id: str,
        username: str,
        password: Optional[str],
        access_token: Optional[str],
        limit: Optional[int],
        force_update: bool,
        use_api: bool,
    ) -> None:
        """
        Execute Instagram post extraction with progress tracking.
        
        This method runs the complete extraction lifecycle:
        1. Mark job as RUNNING
        2. Connect to Instagram via parser
        3. Fetch posts in batches
        4. Update progress and broadcast via WebSocket
        5. Save posts to database
        6. Mark job as COMPLETED or FAILED
        
        Args:
            job_id: UUID of the extraction job
            username: Instagram username to fetch posts from
            password: Account password (for Instaloader)
            access_token: API access token (for Instagram API)
            limit: Maximum posts to fetch
            force_update: Whether to force re-fetch existing posts
            use_api: Whether to use Instagram API (True) or Instaloader (False)
        
        Example:
            >>> await service.run_extraction(
            ...     job_id="550e8400-e29b-41d4-a716-446655440000",
            ...     username="cooking_profile",
            ...     password="secret123",
            ...     access_token=None,
            ...     limit=50,
            ...     force_update=False,
            ...     use_api=False
            ... )
        """
        try:
            # Mark job as running
            self.job_manager.update_job_status(
                job_id, ExtractionStatus.RUNNING, 0, 0, []
            )
            await self.ws_manager.broadcast_progress(
                job_id,
                {
                    "job_id": job_id,
                    "status": "running",
                    "progress": 0,
                    "messages_processed": 0,
                    "errors": [],
                },
            )
            
            logger.info(f"Starting Instagram extraction for job {job_id}")
            
            # Create appropriate parser based on use_api flag
            if use_api:
                # Note: InstagramAPIParser requires user_id which is not provided in the request
                # This is a known limitation - API method needs to be fully implemented
                raise NotImplementedError(
                    "Instagram Platform API extraction is not yet fully implemented. "
                    "Please use use_api=false for Instaloader method."
                )
            else:
                parser = InstaloaderParser(
                    username=username,
                    password=password,
                    session_file=f"instagram_session_{username}",
                )
            
            posts_processed = 0
            last_broadcast_time = time.time()
            broadcast_interval = 5.0  # seconds
            
            # InstaloaderParser is sync, run in thread
            def sync_extraction():
                nonlocal posts_processed
                
                with parser:
                    logger.info(f"Connected to Instagram for job {job_id}")
                    
                    for post_data in parser.get_saved_posts(
                        limit=limit, force_update=force_update
                    ):
                        try:
                            # Save post to database
                            self.db._insert_instagram_post(
                                shortcode=post_data["shortcode"],
                                owner_username=post_data.get("owner_username"),
                                owner_id=post_data.get("owner_id"),
                                caption=post_data.get("caption"),
                                is_video=post_data.get("is_video", False),
                                media_url=post_data.get("media_url"),
                                typename=post_data.get("typename"),
                                likes=post_data.get("likes"),
                                comments=post_data.get("comments"),
                                created_at=post_data.get("created_at"),
                                hashtags=post_data.get("hashtags"),
                                mentions=post_data.get("mentions"),
                                is_saved=post_data.get("is_saved", True),
                                source=post_data.get("source", "saved")
                            )
                            posts_processed += 1
                            
                            # Calculate progress
                            progress = self._calculate_progress(posts_processed, limit)
                            
                            # Update job status
                            self.job_manager.update_job_status(
                                job_id,
                                ExtractionStatus.RUNNING,
                                progress,
                                posts_processed,
                                [],
                            )
                            
                        except Exception as e:
                            logger.error(
                                f"Error saving post in job {job_id}: {e}",
                                exc_info=True,
                            )
                            continue
            
            # Run sync extraction in thread
            await asyncio.to_thread(sync_extraction)
            
            # Mark as completed
            self.job_manager.mark_job_completed(job_id, posts_processed)
            await self.ws_manager.broadcast_progress(
                job_id,
                {
                    "job_id": job_id,
                    "status": "completed",
                    "progress": 100,
                    "messages_processed": posts_processed,
                    "errors": [],
                },
            )
            
            logger.info(
                f"Instagram extraction completed for job {job_id}: "
                f"{posts_processed} posts"
            )
            
        except Exception as e:
            # Handle all errors
            error_msg = f"Extraction error: {str(e)}"
            logger.error(f"Job {job_id} failed: {error_msg}", exc_info=True)
            self.job_manager.mark_job_failed(job_id, error_msg)
            
            job = self.job_manager.get_job(job_id)
            await self.ws_manager.broadcast_progress(
                job_id,
                {
                    "job_id": job_id,
                    "status": "failed",
                    "progress": job.progress if job else 0,
                    "messages_processed": job.messages_processed if job else 0,
                    "errors": [error_msg],
                },
            )
    
    def _calculate_progress(self, current: int, total: Optional[int]) -> int:
        """
        Calculate progress percentage.
        
        Args:
            current: Number of items processed
            total: Total number of items (None if unknown)
        
        Returns:
            Progress percentage (0-100)
        """
        if total is None or total == 0:
            # Unknown total, use logarithmic scale for progress
            return min(95, int(50 + 10 * (current / 100)))
        return min(100, int((current / total) * 100))
