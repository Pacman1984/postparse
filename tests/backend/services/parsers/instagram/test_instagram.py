"""Tests for the Instagram parser module."""
import pytest
from unittest.mock import Mock, patch, AsyncMock, call
from datetime import datetime

from backend.postparse.services.parsers.instagram.instagram_parser import InstaloaderParser, InstagramAPIParser, InstagramRateLimitError
from backend.postparse.core.data.database import SocialMediaDatabase


@pytest.fixture
def mock_instaloader():
    """Create a mock Instaloader instance."""
    with patch('backend.postparse.services.parsers.instagram.instagram_parser.instaloader.Instaloader') as mock:
        yield mock


@pytest.fixture
def mock_post():
    """Create a mock Instagram post."""
    post = Mock()
    post.shortcode = 'abc123'
    post.owner_username = 'test_user'
    post.owner_id = '12345'
    post.caption = 'Test post #test @mention'
    post.date = datetime.now()
    post.is_video = False
    post.url = 'http://example.com/image.jpg'
    post.video_url = None
    post.typename = 'GraphImage'
    post.likes = 100
    post.comments = 10
    post.caption_hashtags = ['test']
    post.caption_mentions = ['mention']
    
    return post


@pytest.fixture
def mock_db():
    """Create a mock database."""
    db = Mock()
    db.post_exists = Mock(return_value=False)
    db._insert_instagram_post = Mock(return_value=1)
    return db


class TestInstaloaderParser:
    """Tests for the InstaloaderParser class."""

    def test_initialization(self, mock_instaloader):
        """Test InstaloaderParser initialization."""
        parser = InstaloaderParser(
            username='test_user',
            password='test_pass',
            min_delay=5.0,
            max_delay=30.0
        )
        assert parser._username == 'test_user'
        assert parser._password == 'test_pass'
        assert parser._min_delay == 5.0
        assert parser._max_delay == 30.0
        assert parser._loader is not None

    @patch('backend.postparse.services.parsers.instagram.instagram_parser.instaloader.Profile')
    def test_get_saved_posts_normal_mode(self, mock_profile, mock_instaloader, mock_post, mock_db):
        """Test getting saved posts in normal mode."""
        # Setup mock profile
        profile_instance = Mock()
        profile_instance.get_saved_posts.return_value = [mock_post]
        mock_profile.from_username.return_value = profile_instance
        
        parser = InstaloaderParser(username='test_user', password='test_pass')
        
        # Test normal mode (no force update)
        posts = list(parser.get_saved_posts(limit=1, db=mock_db, force_update=False))
        assert len(posts) == 1
        
        post = posts[0]
        assert post['shortcode'] == mock_post.shortcode
        assert post['owner_username'] == mock_post.owner_username
        assert post['owner_id'] == str(mock_post.owner_id)
        assert post['caption'] == mock_post.caption
        assert post['is_video'] == mock_post.is_video
        assert post['url'] == mock_post.url
        assert post['typename'] == mock_post.typename
        assert post['likes'] == mock_post.likes
        assert post['comments'] == mock_post.comments
        assert post['hashtags'] == list(mock_post.caption_hashtags)
        assert post['mentions'] == list(mock_post.caption_mentions)
        
        # Verify database check
        mock_db.post_exists.assert_called_once_with(mock_post.shortcode)

    @patch('backend.postparse.services.parsers.instagram.instagram_parser.instaloader.Profile')
    def test_get_saved_posts_force_update(self, mock_profile, mock_instaloader, mock_post, mock_db):
        """Test getting saved posts with force update."""
        # Setup mock profile
        profile_instance = Mock()
        profile_instance.get_saved_posts.return_value = [mock_post]
        mock_profile.from_username.return_value = profile_instance
        
        # Set post to exist in database
        mock_db.post_exists.return_value = True
        
        parser = InstaloaderParser(username='test_user', password='test_pass')
        
        # Test force update mode
        posts = list(parser.get_saved_posts(limit=1, db=mock_db, force_update=True))
        assert len(posts) == 1  # Should still get the post despite it existing
        
        # Verify post exists check wasn't called in force update mode
        mock_db.post_exists.assert_not_called()

    def test_save_posts_to_db_normal_mode(self, mock_instaloader, mock_post, mock_db):
        """Test saving posts to database in normal mode."""
        with patch('backend.postparse.services.parsers.instagram.instagram_parser.instaloader.Profile') as mock_profile:
            profile_instance = Mock()
            profile_instance.get_saved_posts.return_value = [mock_post]
            mock_profile.from_username.return_value = profile_instance
            
            parser = InstaloaderParser(username='test_user', password='test_pass')
            
            # Test normal save
            saved_count = parser.save_posts_to_db(mock_db, limit=1)
            assert saved_count == 1
            
            # Verify database calls - post_exists is called during both get_saved_posts and save_posts_to_db
            assert mock_db.post_exists.call_count == 2
            assert mock_db.post_exists.call_args_list == [
                call(mock_post.shortcode),  # First check in get_saved_posts
                call(mock_post.shortcode)   # Second check in save_posts_to_db
            ]
            mock_db._insert_instagram_post.assert_called_once()

    def test_save_posts_to_db_force_update(self, mock_instaloader, mock_post, mock_db):
        """Test saving posts to database with force update."""
        with patch('backend.postparse.services.parsers.instagram.instagram_parser.instaloader.Profile') as mock_profile:
            profile_instance = Mock()
            profile_instance.get_saved_posts.return_value = [mock_post]
            mock_profile.from_username.return_value = profile_instance
            
            # Set post to exist in database
            mock_db.post_exists.return_value = True
            
            parser = InstaloaderParser(username='test_user', password='test_pass')
            
            # Test force update
            saved_count = parser.save_posts_to_db(mock_db, limit=1, force_update=True)
            assert saved_count == 1
            
            # Verify database calls - post_exists should not be called in force update mode
            mock_db.post_exists.assert_not_called()
            mock_db._insert_instagram_post.assert_called_once()

    @patch('backend.postparse.services.parsers.instagram.instagram_parser.instaloader.Profile')
    def test_rate_limit_handling(self, mock_profile, mock_instaloader):
        """Test handling of rate limit errors."""
        # Setup mock profile to raise rate limit error
        profile_instance = Mock()
        profile_instance.get_saved_posts.side_effect = InstagramRateLimitError("Rate limited")
        mock_profile.from_username.return_value = profile_instance
        
        parser = InstaloaderParser(username='test_user', password='test_pass')
        
        # Test that rate limit error is raised
        with pytest.raises(InstagramRateLimitError):
            list(parser.get_saved_posts(limit=1))


class TestInstagramAPIParser:
    """Tests for the InstagramAPIParser class."""

    @pytest.fixture
    def mock_response(self):
        """Create a mock API response."""
        return {
            'data': [{
                'id': '123',
                'caption': 'Test post #test @mention',
                'media_type': 'IMAGE',
                'media_url': 'http://example.com/image.jpg',
                'permalink': 'http://instagram.com/p/abc123',
                'timestamp': '2023-01-01T12:00:00+0000',
                'username': 'test_user'
            }],
            'paging': {
                'cursors': {
                    'after': 'cursor123'
                },
                'next': 'http://example.com/next'
            }
        }

    def test_initialization(self):
        """Test InstagramAPIParser initialization."""
        parser = InstagramAPIParser(
            access_token='test_token',
            user_id='test_user_id'
        )
        assert parser._access_token == 'test_token'
        assert parser._user_id == 'test_user_id'
        assert parser._base_url == 'https://graph.instagram.com/v12.0'

    @patch('requests.get')
    def test_get_saved_posts(self, mock_get, mock_response):
        """Test getting posts via the API."""
        mock_get.return_value.json.return_value = mock_response
        mock_get.return_value.raise_for_status = Mock()
        
        parser = InstagramAPIParser(access_token='test_token', user_id='test_user_id')
        posts = list(parser.get_saved_posts(limit=1))
        
        assert len(posts) == 1
        post = posts[0]
        assert post['shortcode'] == '123'
        assert post['owner_username'] == 'test_user'
        assert post['caption'] == 'Test post #test @mention'
        assert post['hashtags'] == ['test']
        assert post['mentions'] == ['mention']

    @patch('requests.get')
    def test_api_error_handling(self, mock_get):
        """Test handling of API errors."""
        from requests.exceptions import RequestException
        mock_get.side_effect = RequestException("API Error")
        
        parser = InstagramAPIParser(access_token='test_token', user_id='test_user_id')
        
        with pytest.raises(Exception) as exc_info:
            list(parser.get_saved_posts(limit=1))
        assert "API request failed" in str(exc_info.value) 