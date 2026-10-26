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
from tqdm import tqdm

from postparse.core.data.database import SocialMediaDatabase
from postparse.core.utils.config import get_config, get_paths_config

# Enable nested event loops for Jupyter
nest_asyncio.apply()


class TelegramParser:
    """Handles Telegram data extraction using Telethon."""
    
    def __init__(self, api_id: int, api_hash: str, phone: str = None,
                 session_file: str = "telegram_session",
                 cache_dir: Optional[str] = None,
                 downloads_dir: Optional[str] = None,
                 config_path: Optional[str] = None,
                 interactive: bool = True):
        """Initialize Telegram parser.
        
        Args:
            api_id: Telegram API ID (integer) from https://my.telegram.org
            api_hash: Telegram API hash from https://my.telegram.org
            phone: Phone number in international format (e.g., +1234567890)
            session_file: Name of session file (without path)
            cache_dir: Directory for cache files (sessions). If None, uses config default.
            downloads_dir: Directory for downloaded media files. If None, uses config default.
            config_path: Path to configuration file. If None, uses default locations.
            interactive: If True, prompts for input when needed. If False, raises errors
                for missing credentials. Set to False for API usage.
        """
        # Load configuration
        config = get_config(config_path)
        paths_config = get_paths_config()
        
        self._phone = phone
        self._interactive = interactive
        
        # Use configuration for directories with fallbacks
        cache_dir = cache_dir or config.get('paths.cache_dir', default='data/cache')
        downloads_dir = downloads_dir or config.get('paths.telegram_downloads_dir', default='data/downloads/telegram')
        
        # Create cache and downloads directories
        self._cache_dir = Path(cache_dir)
        self._downloads_dir = Path(downloads_dir)
        self._cache_dir.mkdir(parents=True, exist_ok=True)
        self._downloads_dir.mkdir(parents=True, exist_ok=True)
        
        # Full path to session file
        session_path = self._cache_dir / session_file
        
        # Load Telegram configuration
        connection_retries = config.get('telegram.connection_retries', default=3)
        retry_delay = config.get('telegram.retry_delay', default=1)
        auto_reconnect = config.get('telegram.auto_reconnect', default=True)
        request_retries = config.get('telegram.request_retries', default=3)
        
        # Use configured connection settings
        self._client = TelegramClient(
            str(session_path),
            api_id,
            api_hash,
            connection_retries=connection_retries,
            retry_delay=retry_delay,
            auto_reconnect=auto_reconnect,
            request_retries=request_retries
        )
        self._me = None
        self._request_count = 0
        self._last_request_time = 0
        
        # Store configuration for use in other methods
        self._config = config
    
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
                    timeout = self._config.get('telegram.media_timeout_image', default=30)
                    path = await self._download_media(message, timeout=timeout)
                    if path:
                        media_urls.append(str(path))
                elif isinstance(message.media, MessageMediaDocument):
                    content_type = 'document'
                    timeout = self._config.get('telegram.media_timeout_document', default=60)
                    path = await self._download_media(message, timeout=timeout)
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
        """Async context manager entry.
        
        For API usage (interactive=False), ensure phone is provided and session file exists,
        or authenticate interactively beforehand. Non-interactive mode will raise
        descriptive errors instead of prompting for input.
        """
        await self._client.connect()
        
        if not await self._client.is_user_authorized():
            if not self._phone:
                if self._interactive:
                    self._phone = input("Please enter your phone number in international format (e.g., +1234567890): ")
                else:
                    raise ValueError(
                        "Phone number is required for new sessions. "
                        "Provide phone parameter or ensure session file exists."
                    )
            
            # Send code request
            await self._client.send_code_request(self._phone)
            
            try:
                # Get the verification code from user
                if self._interactive:
                    verification_code = input("Please enter the verification code you received: ")
                else:
                    raise ValueError(
                        "Session requires verification code. "
                        "Please authenticate interactively first or provide valid session file."
                    )
                await self._client.sign_in(self._phone, verification_code)
                
            except SessionPasswordNeededError:
                # 2FA is enabled, ask for password
                if self._interactive:
                    password = input("Please enter your 2FA password: ")
                else:
                    raise ValueError(
                        "Session requires 2FA password. "
                        "Please authenticate interactively first or provide valid session file."
                    )
                await self._client.sign_in(password=password)
        
        self._me = await self._client.get_me()
        # Wait after connection to avoid suspicion (using configured delays)
        delay_min = self._config.get('telegram.connection_delay_min', default=2.0)
        delay_max = self._config.get('telegram.connection_delay_max', default=4.0)
        await asyncio.sleep(random.uniform(delay_min, delay_max))
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Async context manager exit."""
        await self._client.disconnect()
    
    async def _wait_between_requests(self):
        """Implement conservative rate limiting using configured delays."""
        # Get configured delay values
        base_delay = self._config.get('telegram.request_delay_base', default=2.0)
        delay_increment = self._config.get('telegram.request_delay_increment', default=0.5)
        extra_delay_10_min = self._config.get('telegram.extra_delay_every_10_min', default=10.0)
        extra_delay_10_max = self._config.get('telegram.extra_delay_every_10_max', default=15.0)
        long_delay_50_min = self._config.get('telegram.long_delay_every_50_min', default=20.0)
        long_delay_50_max = self._config.get('telegram.long_delay_every_50_max', default=30.0)
        
        # Ensure minimum configured delay between requests
        current_time = asyncio.get_event_loop().time()
        if self._last_request_time:
            elapsed = current_time - self._last_request_time
            min_delay = base_delay + delay_increment
            if elapsed < min_delay:
                sleep_time = random.uniform(base_delay, min_delay)
                await asyncio.sleep(sleep_time)
        
        # Add extra delay every 10 requests
        self._request_count += 1
        if self._request_count % 10 == 0:
            await asyncio.sleep(random.uniform(extra_delay_10_min, extra_delay_10_max))
        
        # Add longer delay every 50 requests to avoid patterns
        if self._request_count % 50 == 0:
            await asyncio.sleep(random.uniform(long_delay_50_min, long_delay_50_max))
        
        self._last_request_time = current_time
    
    async def get_saved_messages(self, limit: Optional[int] = None,
                               max_requests_per_session: Optional[int] = None,
                               db: Optional[SocialMediaDatabase] = None,
                               force_update: bool = False) -> Generator[Dict[str, Any], None, None]:
        """Extract saved messages from Telegram.
        
        Args:
            limit: Maximum number of messages to extract (None for all)
            max_requests_per_session: Maximum number of API requests per session (None for no limit)
            db: Optional database to check for existing messages
            force_update: If True, fetch all messages regardless of database state
            
        Yields:
            Dict containing message data
        """
        self._request_count = 0
        message_count = 0
        skipped_count = 0
        total_messages = None
        pbar = None
        
        try:
            # Get all messages first to show progress
            messages = []
            async for message in self._client.iter_messages('me', limit=limit):
                messages.append(message)
            
            total_messages = len(messages)
            desc = "Checking messages" if limit and limit <= 100 else ("Fetching messages (force update)" if force_update else "Fetching messages")
            # Show if this is a sample or full extraction
            if limit and limit <= 100:
                print(f"Sampling {total_messages} newest messages (limit: {limit})...")
            else:
                print(f"Found {total_messages} saved messages{' (force update)' if force_update else ''}")
            pbar = tqdm(total=total_messages, desc=desc, unit="msg")
            
            for message in messages:
                # Check request limits if they exist
                if max_requests_per_session is not None and self._request_count >= max_requests_per_session:
                    print("Reached maximum requests per session. Please wait before making more requests.")
                    break
                
                try:
                    # Only check database if not forcing update
                    if db and not force_update:
                        exists = db.message_exists(message.id)
                        if exists:
                            skipped_count += 1
                            if pbar:
                                pbar.set_postfix({
                                    'processed': message_count,
                                    'skipped': skipped_count,
                                    'mode': 'force update' if force_update else 'normal'
                                })
                                pbar.update(1)
                            continue
                    
                    await self._wait_between_requests()
                    
                    # Update progress with current delay
                    if pbar:
                        delay = 2 + (self._request_count // 10) * 0.5  # Approximate delay
                        pbar.set_description(f"{'Updating' if force_update else 'Fetching'} messages (delay: {delay:.1f}s)")
                        pbar.set_postfix({
                            'processed': message_count,
                            'skipped': skipped_count,
                            'mode': 'force update' if force_update else 'normal'
                        })
                    
                    message_data = await self._parse_message(message)
                    
                    # Always update progress bar
                    if pbar:
                        pbar.update(1)
                    
                    if message_data:
                        yield message_data
                        message_count += 1
                    
                    # Check if we've reached the limit after processing
                    if limit and (message_count + skipped_count) >= limit:
                        break
                    
                except Exception as e:
                    print(f"Error processing message {message.id}: {str(e)}")
                    if pbar:
                        pbar.update(1)
                    continue
                
        except Exception as e:
            print(f"Error fetching messages: {str(e)}")
            raise
        finally:
            if pbar:
                pbar.close()
            if total_messages:
                status = "Force update" if force_update else "Normal fetch"
                print(f"{status} completed. Processed: {message_count}, Skipped: {skipped_count}, Total: {total_messages}")
    
    async def save_messages_to_db(self, db: SocialMediaDatabase, limit: Optional[int] = None,
                                max_requests_per_session: Optional[int] = None, force_update: bool = False) -> int:
        """Save Telegram messages to database.
        
        Args:
            db: Database instance
            limit: Maximum number of messages to save
            max_requests_per_session: Maximum number of API requests per session (None for no limit)
            force_update: If True, will update existing messages. If False, skips existing messages.
            
        Returns:
            Number of messages saved
        """
        saved_count = 0
        updated_count = 0
        
        try:
            # Pass database to get_saved_messages to enable early skipping
            messages = []
            async for message_data in self.get_saved_messages(
                limit=limit,
                max_requests_per_session=max_requests_per_session,
                db=db,
                force_update=force_update
            ):
                messages.append(message_data)
            
            total_messages = len(messages)
            if total_messages == 0:
                print("No messages to process")
                return 0
            
            action = "update" if force_update else "save"
            print(f"Found {total_messages} messages to {action}")
            
            # Now show progress for database saving
            with tqdm(total=total_messages, desc=f"{'Updating' if force_update else 'Saving'} to database", unit="msg") as pbar:
                for message_data in messages:
                    try:
                        exists = db.message_exists(message_data['message_id'])
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
                            if exists:
                                updated_count += 1
                            else:
                                saved_count += 1
                            pbar.set_postfix({
                                'new': saved_count,
                                'updated': updated_count,
                                'total': total_messages
                            })
                        
                        # Add small delay after save
                        await asyncio.sleep(random.uniform(0.1, 0.3))
                        
                    except Exception as e:
                        print(f"Error saving message {message_data['message_id']}: {str(e)}")
                        continue
                    
                    pbar.update(1)
                
        except Exception as e:
            print(f"Error during message saving: {str(e)}")
            print("Partial data may have been saved. Please check the database.")
        
        # Final summary
        if force_update:
            print(f"Process completed. Updated: {updated_count}, New: {saved_count}, Total processed: {total_messages}")
        else:
            print(f"Process completed. Saved: {saved_count}, Total new messages: {total_messages}")
        
        return saved_count + updated_count


def save_telegram_messages(api_id: str, api_hash: str, phone: str = None,
                         db_path: Optional[str] = None,
                         session_file: str = "telegram_session",
                         cache_dir: Optional[str] = None,
                         downloads_dir: Optional[str] = None,
                         limit: Optional[int] = None,
                         max_requests_per_session: Optional[int] = None,
                         force_update: bool = False,
                         config_path: Optional[str] = None) -> int:
    """Helper function to save Telegram messages without dealing with async code.
    
    Args:
        api_id: Telegram API ID
        api_hash: Telegram API hash
        phone: Phone number in international format (e.g., +1234567890)
        db_path: Path to SQLite database. If None, uses config default.
        session_file: Name of session file (without path)
        cache_dir: Directory for cache files (sessions). If None, uses config default.
        downloads_dir: Directory for downloaded media files. If None, uses config default.
        limit: Maximum number of messages to save
        max_requests_per_session: Maximum number of API requests per session
        force_update: If True, will update existing messages. If False, skips existing messages.
        config_path: Path to configuration file. If None, uses default locations.
        
    Returns:
        Number of messages saved
    """
    async def _save():
        # Load configuration for default values
        config = get_config(config_path)
        
        # Use configured defaults if not provided
        final_db_path = db_path or config.get('database.default_db_path', default='social_media.db')
        
        db = SocialMediaDatabase(final_db_path)
        async with TelegramParser(
            api_id=api_id,
            api_hash=api_hash,
            phone=phone,
            session_file=session_file,
            cache_dir=cache_dir,
            downloads_dir=downloads_dir,
            config_path=config_path
        ) as parser:
            return await parser.save_messages_to_db(db, limit, max_requests_per_session, force_update)
    
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