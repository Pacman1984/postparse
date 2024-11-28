"""Telegram parser module for extracting saved messages.

This module uses Telethon to safely extract saved messages from Telegram.
"""
from typing import Generator, Dict, Any, Optional, List
from datetime import datetime
import json
import asyncio
import random
import nest_asyncio
import os
from pathlib import Path
from telethon import TelegramClient
from telethon.errors import SessionPasswordNeededError
from telethon.tl.types import Message, MessageMediaPhoto, MessageMediaDocument

from ..data.database import SocialMediaDatabase

# Enable nested event loops for Jupyter
nest_asyncio.apply()


class TelegramParser:
    """Handles Telegram data extraction using Telethon."""
    
    def __init__(self, api_id: str, api_hash: str, phone: str = None,
                 session_file: str = "telegram_session",
                 cache_dir: str = "data/cache",
                 downloads_dir: str = "data/downloads/telegram"):
        """Initialize Telegram parser.
        
        Args:
            api_id: Telegram API ID from https://my.telegram.org
            api_hash: Telegram API hash from https://my.telegram.org
            phone: Phone number in international format (e.g., +1234567890)
            session_file: Name of session file (without path)
            cache_dir: Directory for cache files (sessions)
            downloads_dir: Directory for downloaded media files
        """
        self._phone = phone
        
        # Create cache and downloads directories
        self._cache_dir = Path(cache_dir)
        self._downloads_dir = Path(downloads_dir)
        self._cache_dir.mkdir(parents=True, exist_ok=True)
        self._downloads_dir.mkdir(parents=True, exist_ok=True)
        
        # Full path to session file
        session_path = self._cache_dir / session_file
        
        # Use conservative connection settings
        self._client = TelegramClient(
            str(session_path),
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
    
    def _get_media_path(self, message: Message, filename: str) -> Path:
        """Get path for downloaded media file.
        
        Args:
            message: Telegram message containing the media
            filename: Original filename
        
        Returns:
            Path object for the media file
        """
        # Use message creation date for directory structure
        message_date = message.date
        date_path = self._downloads_dir / str(message_date.year) / f"{message_date.month:02d}" / f"{message_date.day:02d}"
        date_path.mkdir(parents=True, exist_ok=True)
        
        # Clean filename and add message ID
        clean_filename = "".join(c for c in filename if c.isalnum() or c in "._- ")
        return date_path / f"{message.id}_{clean_filename}"
    
    async def _download_media(self, message: Message, timeout: int = 60) -> Optional[str]:
        """Download media from message with proper file organization.
        
        Args:
            message: Telegram message with media
            timeout: Download timeout in seconds
            
        Returns:
            Path to downloaded file or None if download failed
        """
        try:
            # Get original filename
            filename = getattr(message.media, 'document', None)
            if filename:
                filename = filename.attributes[-1].file_name
            else:
                # For photos, create a filename with message timestamp
                ext = '.jpg' if isinstance(message.media, MessageMediaPhoto) else '.unknown'
                filename = f"media_{int(message.date.timestamp())}{ext}"
            
            # Get proper path for the file using message creation date
            file_path = self._get_media_path(message, filename)
            
            # Download with timeout
            path = await asyncio.wait_for(
                message.download_media(file=str(file_path)),
                timeout=timeout
            )
            
            return path
        except asyncio.TimeoutError:
            print(f"Timeout downloading media for message {message.id}")
            return None
        except Exception as e:
            print(f"Error downloading media for message {message.id}: {str(e)}")
            return None
    
    async def _parse_message(self, message: Message) -> Dict[str, Any]:
        """Parse Telegram message into standardized format.
        
        Args:
            message: Telethon Message object
            
        Returns:
            Dict containing message data
        """
        try:
            # Determine content type and handle media
            media_urls = []
            content_type = 'text'
            
            if message.media:
                if isinstance(message.media, MessageMediaPhoto):
                    content_type = 'image'
                    path = await self._download_media(message, timeout=30)
                    if path:
                        media_urls.append(str(path))
                elif isinstance(message.media, MessageMediaDocument):
                    content_type = 'document'
                    path = await self._download_media(message, timeout=60)
                    if path:
                        media_urls.append(str(path))
            
            # Extract hashtags from entities
            hashtags = []
            if message.entities:
                for entity in message.entities:
                    if entity.__class__.__name__ == 'MessageEntityHashtag':
                        # Extract hashtag text from the message
                        hashtag = message.text[entity.offset:entity.offset + entity.length]
                        if hashtag.startswith('#'):
                            hashtag = hashtag[1:]  # Remove # symbol
                        hashtags.append(hashtag)
            
            return {
                'message_id': message.id,
                'chat_id': message.chat_id if hasattr(message, 'chat_id') else None,
                'content': message.text if message.text else None,
                'content_type': content_type,
                'media_urls': media_urls,
                'views': message.views if hasattr(message, 'views') else None,
                'forwards': message.forwards if hasattr(message, 'forwards') else None,
                'reply_to_msg_id': message.reply_to_msg_id if message.reply_to_msg_id else None,
                'created_at': message.date,
                'hashtags': hashtags
            }
        except Exception as e:
            print(f"Error parsing message attributes: {str(e)}")
            return None
    
    async def __aenter__(self):
        """Async context manager entry."""
        await self._client.connect()
        
        if not await self._client.is_user_authorized():
            if not self._phone:
                self._phone = input("Please enter your phone number in international format (e.g., +1234567890): ")
            
            # Send code request
            await self._client.send_code_request(self._phone)
            
            try:
                # Get the verification code from user
                verification_code = input("Please enter the verification code you received: ")
                await self._client.sign_in(self._phone, verification_code)
                
            except SessionPasswordNeededError:
                # 2FA is enabled, ask for password
                password = input("Please enter your 2FA password: ")
                await self._client.sign_in(password=password)
        
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
                    message_data = await self._parse_message(message)
                    if message_data:
                        yield message_data
                        message_count += 1
                except Exception as e:
                    print(f"Error processing message {message.id}: {str(e)}")
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
                try:
                    msg_id = db._insert_telegram_message(
                        message_id=message_data['message_id'],
                        chat_id=message_data['chat_id'],
                        content=message_data['content'],
                        content_type=message_data['content_type'],
                        media_urls=message_data['media_urls'],
                        views=message_data['views'],
                        forwards=message_data['forwards'],
                        reply_to_msg_id=message_data['reply_to_msg_id'],
                        created_at=message_data['created_at'],
                        hashtags=message_data['hashtags']
                    )
                    
                    if msg_id:
                        saved_count += 1
                        # Add extra random delay after successful save
                        await asyncio.sleep(random.uniform(1, 2))
                except Exception as e:
                    print(f"Error saving message {message_data['message_id']}: {str(e)}")
                    continue
        except Exception as e:
            print(f"Error during message saving: {str(e)}")
            print("Partial data may have been saved. Please check the database.")
        
        return saved_count


def save_telegram_messages(api_id: str, api_hash: str, phone: str = None,
                         db_path: str = "social_media.db",
                         session_file: str = "telegram_session",
                         cache_dir: str = "data/cache",
                         downloads_dir: str = "data/downloads/telegram",
                         limit: Optional[int] = None,
                         max_requests_per_session: int = 100) -> int:
    """Helper function to save Telegram messages without dealing with async code.
    
    Args:
        api_id: Telegram API ID
        api_hash: Telegram API hash
        phone: Phone number in international format (e.g., +1234567890)
        db_path: Path to SQLite database
        session_file: Name of session file (without path)
        cache_dir: Directory for cache files (sessions)
        downloads_dir: Directory for downloaded media files
        limit: Maximum number of messages to save
        max_requests_per_session: Maximum number of API requests per session
        
    Returns:
        Number of messages saved
    """
    async def _save():
        db = SocialMediaDatabase(db_path)
        async with TelegramParser(
            api_id=api_id,
            api_hash=api_hash,
            phone=phone,
            session_file=session_file,
            cache_dir=cache_dir,
            downloads_dir=downloads_dir
        ) as parser:
            return await parser.save_messages_to_db(db, limit, max_requests_per_session)
    
    try:
        # Try to get the running event loop
        loop = asyncio.get_event_loop()
        if loop.is_running():
            # If we're in a Jupyter notebook, create a new loop
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
        return loop.run_until_complete(_save())
    except RuntimeError:
        # If we still have issues, create a new loop
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        return loop.run_until_complete(_save()) 