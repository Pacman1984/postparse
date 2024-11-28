"""Telegram parser module for extracting saved messages.

This module uses Telethon to safely extract saved messages from Telegram.
"""
from typing import Generator, Dict, Any, Optional, List
from datetime import datetime
import json
import asyncio
import random
from telethon import TelegramClient
from telethon.tl.types import Message, MessageMediaPhoto, MessageMediaDocument

from ..data.database import SocialMediaDatabase


class TelegramParser:
    """Handles Telegram data extraction using Telethon."""
    
    def __init__(self, api_id: str, api_hash: str, session_file: str = "telegram_session"):
        """Initialize Telegram parser.
        
        Args:
            api_id: Telegram API ID from https://my.telegram.org
            api_hash: Telegram API hash from https://my.telegram.org
            session_file: Path to session file for cached login
        """
        # Use conservative connection settings
        self._client = TelegramClient(
            session_file,
            api_id,
            api_hash,
            connection_retries=3,  # Limit connection retries
            retry_delay=1,  # Wait between retries
            auto_reconnect=True,  # Enable auto reconnect
            request_retries=3  # Limit request retries
        )
        self._me = None
        self._request_count = 0
        self._last_request_time = 0
    
    async def __aenter__(self):
        """Async context manager entry."""
        await self._client.start()
        self._me = await self._client.get_me()
        # Wait after connection to avoid suspicion
        await asyncio.sleep(random.uniform(2, 4))
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Async context manager exit."""
        await self._client.disconnect()
    
    async def _wait_between_requests(self):
        """Implement conservative rate limiting."""
        # Ensure minimum 2-4 seconds between requests
        current_time = asyncio.get_event_loop().time()
        if self._last_request_time:
            elapsed = current_time - self._last_request_time
            if elapsed < 4:
                sleep_time = random.uniform(2, 4)
                await asyncio.sleep(sleep_time)
        
        # Add extra delay every 10 requests
        self._request_count += 1
        if self._request_count % 10 == 0:
            await asyncio.sleep(random.uniform(10, 15))
        
        # Add longer delay every 50 requests to avoid patterns
        if self._request_count % 50 == 0:
            await asyncio.sleep(random.uniform(20, 30))
        
        self._last_request_time = current_time
    
    async def _parse_message(self, message: Message) -> Dict[str, Any]:
        """Parse Telegram message into standardized format.
        
        Args:
            message: Telethon Message object
            
        Returns:
            Dict containing parsed message data
        """
        media_urls = []
        content_type = 'text'
        
        if message.media:
            try:
                if isinstance(message.media, MessageMediaPhoto):
                    content_type = 'image'
                    # Download photo to get URL with timeout
                    path = await asyncio.wait_for(
                        message.download_media(),
                        timeout=30  # 30 seconds timeout for media download
                    )
                    if path:
                        media_urls.append(str(path))
                elif isinstance(message.media, MessageMediaDocument):
                    content_type = 'document'
                    # Download document to get URL with timeout
                    path = await asyncio.wait_for(
                        message.download_media(),
                        timeout=60  # 60 seconds timeout for document download
                    )
                    if path:
                        media_urls.append(str(path))
            except asyncio.TimeoutError:
                print(f"Timeout downloading media for message {message.id}")
            except Exception as e:
                print(f"Error downloading media for message {message.id}: {str(e)}")
        
        return {
            'platform': 'telegram',
            'platform_id': str(message.id),
            'content_type': content_type,
            'content': message.message if message.message else None,
            'media_urls': media_urls,
            'metadata': {
                'views': message.views if hasattr(message, 'views') else None,
                'forwards': message.forwards if hasattr(message, 'forwards') else None,
                'reply_to_msg_id': message.reply_to_msg_id,
                'entities': [
                    {
                        'type': entity.__class__.__name__,
                        'offset': entity.offset,
                        'length': entity.length
                    }
                    for entity in (message.entities or [])
                ]
            },
            'created_at': message.date
        }
    
    async def get_saved_messages(self, limit: Optional[int] = None,
                               max_requests_per_session: int = 100) -> Generator[Dict[str, Any], None, None]:
        """Extract saved messages from Telegram.
        
        Args:
            limit: Maximum number of messages to extract (None for all)
            max_requests_per_session: Maximum number of API requests per session
            
        Yields:
            Dict containing message data
        """
        self._request_count = 0
        message_count = 0
        
        try:
            async for message in self._client.iter_messages('me', limit=limit):
                # Check request limits
                if self._request_count >= max_requests_per_session:
                    print("Reached maximum requests per session. Please wait before making more requests.")
                    break
                
                try:
                    await self._wait_between_requests()
                    yield await self._parse_message(message)
                    message_count += 1
                except Exception as e:
                    print(f"Error parsing message {message.id}: {str(e)}")
                    continue
        except Exception as e:
            print(f"Error fetching messages: {str(e)}")
    
    async def save_messages_to_db(self, db: SocialMediaDatabase, limit: Optional[int] = None,
                                max_requests_per_session: int = 100) -> int:
        """Save Telegram messages to database.
        
        Args:
            db: Database instance
            limit: Maximum number of messages to save
            max_requests_per_session: Maximum number of API requests per session
            
        Returns:
            Number of messages saved
        """
        saved_count = 0
        
        try:
            async for message_data in self.get_saved_messages(limit, max_requests_per_session):
                post_id = db._insert_post(
                    platform=message_data['platform'],
                    platform_id=message_data['platform_id'],
                    content_type=message_data['content_type'],
                    content=message_data['content'],
                    media_urls=message_data['media_urls'],
                    metadata=message_data['metadata'],
                    created_at=message_data['created_at']
                )
                
                if post_id:
                    # Extract and add hashtags from entities
                    hashtags = [
                        entity['text']
                        for entity in message_data['metadata'].get('entities', [])
                        if entity['type'] == 'MessageEntityHashtag'
                    ]
                    if hashtags:
                        db._add_tags(post_id, hashtags)
                    saved_count += 1
                    
                    # Add extra random delay after successful save
                    await asyncio.sleep(random.uniform(1, 2))
        except Exception as e:
            print(f"Error during message saving: {str(e)}")
            print("Partial data may have been saved. Please check the database.")
        
        return saved_count


def save_telegram_messages(api_id: str, api_hash: str, db_path: str = "social_media.db",
                         session_file: str = "telegram_session", limit: Optional[int] = None,
                         max_requests_per_session: int = 100) -> int:
    """Helper function to save Telegram messages without dealing with async code.
    
    Args:
        api_id: Telegram API ID
        api_hash: Telegram API hash
        db_path: Path to SQLite database
        session_file: Path to Telegram session file
        limit: Maximum number of messages to save
        max_requests_per_session: Maximum number of API requests per session
        
    Returns:
        Number of messages saved
    """
    async def _save():
        db = SocialMediaDatabase(db_path)
        async with TelegramParser(api_id, api_hash, session_file) as parser:
            return await parser.save_messages_to_db(db, limit, max_requests_per_session)
    
    return asyncio.get_event_loop().run_until_complete(_save()) 