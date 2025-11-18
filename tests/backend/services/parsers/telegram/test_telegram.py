"""Tests for the Telegram parser module."""
import pytest
from unittest.mock import Mock, patch, AsyncMock, call
from datetime import datetime
from telethon.tl.types import MessageMediaPhoto
import asyncio

from postparse.services.parsers.telegram.telegram_parser import TelegramParser
from postparse.core.data.database import SocialMediaDatabase


def run_async(coro):
    """Helper function to run coroutines synchronously."""
    try:
        loop = asyncio.get_event_loop()
    except RuntimeError:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
    return loop.run_until_complete(coro)


def create_mock_message(**kwargs):
    """Helper function to create a mock message with default values."""
    message = Mock()
    message.id = kwargs.get('id', 123)
    message.chat_id = kwargs.get('chat_id', 456)
    message.text = kwargs.get('text', "Test message #test")
    message.date = kwargs.get('date', datetime.now())
    message.views = kwargs.get('views', 100)
    message.forwards = kwargs.get('forwards', 5)
    message.reply_to_msg_id = kwargs.get('reply_to_msg_id', None)
    message.media = kwargs.get('media', None)
    
    # Mock entities (hashtags, mentions, etc.)
    entity = Mock()
    entity.__class__.__name__ = "MessageEntityHashtag"
    entity.offset = 13
    entity.length = 5
    message.entities = [entity]
    
    return message


@pytest.fixture
def mock_telegram_client():
    """Create a mock TelegramClient instance."""
    with patch('postparse.services.parsers.telegram.telegram_parser.TelegramClient') as mock:
        client_instance = Mock()
        
        # Mock context manager methods
        async def mock_aenter(*args, **kwargs):
            return client_instance
        async def mock_aexit(*args, **kwargs):
            pass
        
        client_instance.__aenter__ = mock_aenter
        client_instance.__aexit__ = mock_aexit
        client_instance.is_user_authorized = AsyncMock(return_value=True)
        client_instance.get_me = AsyncMock(return_value=Mock(id=123))
        client_instance.connect = AsyncMock()
        client_instance.disconnect = AsyncMock()
        
        # Mock iter_messages to return a list of messages
        mock_messages = [create_mock_message()]
        async def mock_iter_messages(*args, **kwargs):
            for msg in mock_messages:
                yield msg
        client_instance.iter_messages = mock_iter_messages
        
        # Mock download_media
        async def mock_download_media(*args, **kwargs):
            return "/path/to/media.jpg"
        client_instance.download_media = mock_download_media
        
        mock.return_value = client_instance
        yield mock


@pytest.fixture
def mock_db():
    """Create a mock database."""
    db = Mock()
    db.message_exists = Mock(return_value=False)
    db._insert_telegram_message = Mock(return_value=1)
    return db


class TestTelegramParser:
    """Tests for the TelegramParser class."""

    def test_initialization(self, mock_telegram_client):
        """Test TelegramParser initialization."""
        parser = TelegramParser(api_id="test_id", api_hash="test_hash")
        assert parser._client is not None
        assert parser._request_count == 0

    def test_parse_message(self, mock_telegram_client):
        """Test parsing a Telegram message."""
        parser = TelegramParser(api_id="test_id", api_hash="test_hash")
        mock_message = create_mock_message()
        
        # Run async parse_message synchronously
        parsed_message = run_async(parser._parse_message(mock_message))
        
        assert parsed_message['message_id'] == mock_message.id
        assert parsed_message['chat_id'] == mock_message.chat_id
        assert parsed_message['content'] == mock_message.text
        assert parsed_message['content_type'] == 'text'
        assert parsed_message['views'] == mock_message.views
        assert parsed_message['forwards'] == mock_message.forwards
        assert parsed_message['hashtags'] == ['test']

    def test_get_saved_messages_normal_mode(self, mock_telegram_client, mock_db):
        """Test getting saved messages in normal mode."""
        parser = TelegramParser(api_id="test_id", api_hash="test_hash")
        
        # Run async context manager and get_saved_messages synchronously
        async def get_messages():
            async with parser:
                return [msg async for msg in parser.get_saved_messages(
                    limit=1,
                    db=mock_db,
                    force_update=False
                )]
        
        messages = run_async(get_messages())
        
        assert len(messages) == 1
        message = messages[0]
        assert message['message_id'] == 123
        assert message['content'] == "Test message #test"
        
        # Verify database check
        mock_db.message_exists.assert_called_once_with(123)

    def test_get_saved_messages_force_update(self, mock_telegram_client, mock_db):
        """Test getting saved messages with force update."""
        mock_db.message_exists.return_value = True
        parser = TelegramParser(api_id="test_id", api_hash="test_hash")
        
        async def get_messages():
            async with parser:
                return [msg async for msg in parser.get_saved_messages(
                    limit=1,
                    db=mock_db,
                    force_update=True
                )]
        
        messages = run_async(get_messages())
        
        assert len(messages) == 1
        mock_db.message_exists.assert_not_called()

    def test_save_messages_to_db_normal_mode(self, mock_telegram_client, mock_db):
        """Test saving messages to database in normal mode."""
        parser = TelegramParser(api_id="test_id", api_hash="test_hash")
        
        async def save_messages():
            async with parser:
                return await parser.save_messages_to_db(mock_db, limit=1)
        
        saved_count = run_async(save_messages())
        
        assert saved_count == 1
        assert mock_db.message_exists.call_count == 2
        assert mock_db.message_exists.call_args_list == [
            call(123),  # First check in get_saved_messages
            call(123)   # Second check in save_messages_to_db
        ]
        mock_db._insert_telegram_message.assert_called_once()

    def test_save_messages_to_db_force_update(self, mock_telegram_client, mock_db):
        """Test saving messages to database with force update."""
        mock_db.message_exists.return_value = True
        parser = TelegramParser(api_id="test_id", api_hash="test_hash")
        
        async def save_messages():
            async with parser:
                return await parser.save_messages_to_db(
                    mock_db,
                    limit=1,
                    force_update=True
                )
        
        saved_count = run_async(save_messages())
        
        assert saved_count == 1
        mock_db.message_exists.assert_called_once_with(123)
        mock_db._insert_telegram_message.assert_called_once()

    def test_media_download(self, mock_telegram_client):
        """Test media download functionality."""
        # Create a mock message with media
        mock_message = create_mock_message(media=MessageMediaPhoto(None, None))
        
        # Set up the mock download_media function
        async def mock_download_media(*args, **kwargs):
            return "/path/to/media.jpg"
        mock_message.download_media = mock_download_media
        
        parser = TelegramParser(api_id="test_id", api_hash="test_hash")
        path = run_async(parser._download_media(mock_message))
        assert path == "/path/to/media.jpg"

    def test_media_download_timeout(self, mock_telegram_client):
        """Test media download timeout handling."""
        mock_message = create_mock_message()
        
        # Mock download_media to raise TimeoutError
        async def mock_download_timeout(*args, **kwargs):
            raise asyncio.TimeoutError()
        mock_message.download_media = mock_download_timeout
        
        parser = TelegramParser(api_id="test_id", api_hash="test_hash")
        path = run_async(parser._download_media(mock_message, timeout=1))
        assert path is None
    