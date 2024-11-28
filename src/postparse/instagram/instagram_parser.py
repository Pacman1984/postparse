"""Instagram parser module for extracting saved posts.

This module uses Instaloader to safely extract saved posts from Instagram.
"""
import time
import random
from typing import Generator, Dict, Any, Optional, List
from pathlib import Path
import instaloader
from datetime import datetime

from ..data.database import SocialMediaDatabase


class InstagramParser:
    """Handles Instagram data extraction using Instaloader."""
    
    def __init__(self, username: Optional[str] = None, password: Optional[str] = None,
                 session_file: Optional[str] = None):
        """Initialize Instagram parser.
        
        Args:
            username: Instagram username
            password: Instagram password
            session_file: Path to session file for cached login
        """
        self._loader = instaloader.Instaloader(
            sleep=True,  # Enable sleep between requests
            quiet=False,  # Show progress
            download_pictures=False,  # Don't download media by default
            download_videos=False,
            download_video_thumbnails=False,
            download_geotags=False,
            download_comments=False,
            save_metadata=False,
            max_connection_attempts=3  # Limit retry attempts
        )
        self._username = username
        self._session_file = session_file
        self._request_count = 0
        self._last_request_time = 0
        self.__login(password)
    
    def __login(self, password: Optional[str] = None):
        """Login to Instagram using provided credentials or session file.
        
        Args:
            password: Instagram password
        """
        try:
            if self._session_file and Path(self._session_file).exists():
                # Try to load session from file
                self._loader.load_session_from_file(self._username, self._session_file)
            elif self._username and password:
                # Login with credentials
                self._loader.login(self._username, password)
                # Save session for future use
                if self._session_file:
                    self._loader.save_session_to_file(self._session_file)
            # Wait after login to avoid suspicion
            time.sleep(random.uniform(2, 4))
        except Exception as e:
            print(f"Login failed: {str(e)}")
            raise
    
    def _wait_between_requests(self):
        """Implement conservative rate limiting."""
        # Ensure minimum 3-5 seconds between requests
        current_time = time.time()
        if self._last_request_time:
            elapsed = current_time - self._last_request_time
            if elapsed < 5:
                sleep_time = random.uniform(3, 5)
                time.sleep(sleep_time)
        
        # Add extra delay every 10 requests
        self._request_count += 1
        if self._request_count % 10 == 0:
            time.sleep(random.uniform(15, 20))
        
        # Add longer delay every 50 requests to avoid patterns
        if self._request_count % 50 == 0:
            time.sleep(random.uniform(30, 45))
        
        self._last_request_time = time.time()
    
    def _parse_post(self, post: instaloader.Post) -> Dict[str, Any]:
        """Parse Instagram post into standardized format.
        
        Args:
            post: Instaloader Post object
            
        Returns:
            Dict containing parsed post data
        """
        try:
            # Get media URL
            url = None
            if hasattr(post, 'video_url') and post.is_video:
                url = post.video_url
            elif hasattr(post, 'url'):
                url = post.url
            
            # Get hashtags and mentions from caption
            hashtags = []
            mentions = []
            if post.caption:
                # Use caption_hashtags if available, otherwise parse manually
                if hasattr(post, 'caption_hashtags'):
                    hashtags = post.caption_hashtags
                else:
                    hashtags = [word[1:] for word in post.caption.split() 
                              if word.startswith('#')]
                
                # Use caption_mentions if available, otherwise parse manually
                if hasattr(post, 'caption_mentions'):
                    mentions = post.caption_mentions
                else:
                    mentions = [word[1:] for word in post.caption.split() 
                              if word.startswith('@')]
            
            return {
                'shortcode': post.shortcode,
                'owner_username': post.owner_username if hasattr(post, 'owner_username') else None,
                'owner_id': post.owner_id if hasattr(post, 'owner_id') else None,
                'caption': post.caption,
                'is_video': post.is_video if hasattr(post, 'is_video') else False,
                'url': url,
                'typename': post.typename if hasattr(post, 'typename') else None,
                'likes': post.likes if hasattr(post, 'likes') else None,
                'comments': post.comments if hasattr(post, 'comments') else None,
                'created_at': post.date,
                'hashtags': hashtags,
                'mentions': mentions
            }
        except Exception as e:
            print(f"Error parsing post attributes: {str(e)}")
            return None
    
    def get_saved_posts(self, limit: Optional[int] = None,
                       max_requests_per_session: int = 100) -> Generator[Dict[str, Any], None, None]:
        """Extract saved posts from Instagram.
        
        Args:
            limit: Maximum number of posts to extract (None for all)
            max_requests_per_session: Maximum number of API requests per session
            
        Yields:
            Dict containing post data
        """
        if not self._username:
            raise ValueError("Username is required to fetch saved posts")
        
        try:
            profile = instaloader.Profile.from_username(self._loader.context, self._username)
            count = 0
            self._request_count = 0
            
            for post in profile.get_saved_posts():
                # Check request limits
                if self._request_count >= max_requests_per_session:
                    print("Reached maximum requests per session. Please wait before making more requests.")
                    break
                
                if limit and count >= limit:
                    break
                
                try:
                    self._wait_between_requests()
                    post_data = self._parse_post(post)
                    if post_data:
                        yield post_data
                        count += 1
                except Exception as e:
                    print(f"Error processing post {post.shortcode}: {str(e)}")
                    continue
        except Exception as e:
            print(f"Error fetching saved posts: {str(e)}")
    
    def save_posts_to_db(self, db: SocialMediaDatabase, limit: Optional[int] = None,
                        max_requests_per_session: int = 100) -> int:
        """Save Instagram posts to database.
        
        Args:
            db: Database instance
            limit: Maximum number of posts to save
            max_requests_per_session: Maximum number of API requests per session
            
        Returns:
            Number of posts saved
        """
        saved_count = 0
        
        try:
            for post_data in self.get_saved_posts(limit, max_requests_per_session):
                try:
                    post_id = db._insert_instagram_post(
                        shortcode=post_data['shortcode'],
                        owner_username=post_data['owner_username'],
                        owner_id=post_data['owner_id'],
                        caption=post_data['caption'],
                        is_video=post_data['is_video'],
                        media_url=post_data['url'],
                        typename=post_data['typename'],
                        likes=post_data['likes'],
                        comments=post_data['comments'],
                        created_at=post_data['created_at'],
                        hashtags=post_data['hashtags'],
                        mentions=post_data['mentions'],
                        is_saved=True,
                        source='saved'
                    )
                    
                    if post_id:
                        saved_count += 1
                        # Add extra random delay after successful save
                        time.sleep(random.uniform(1, 2))
                except Exception as e:
                    print(f"Error saving post {post_data['shortcode']}: {str(e)}")
                    continue
        except Exception as e:
            print(f"Error during post saving: {str(e)}")
            print("Partial data may have been saved. Please check the database.")
        
        return saved_count 