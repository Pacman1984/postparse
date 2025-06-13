"""Instagram parser module for extracting saved posts.

This module provides two approaches for extracting Instagram data:
1. Using Instaloader (legacy approach)
2. Using Instagram Platform API (recommended approach)
"""
import time
import random
from typing import Generator, Dict, Any, Optional, List, Set
from pathlib import Path
import instaloader
from datetime import datetime
import requests
from tqdm import tqdm
import logging
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type
import concurrent.futures
import threading

from ..data.database import SocialMediaDatabase
from ..utils.config import get_config

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class InstagramRateLimitError(Exception):
    """Raised when Instagram rate limits are hit."""
    pass

class InstagramAPIError(Exception):
    """Raised when Instagram API encounters an error."""
    pass

class BaseInstagramParser:
    """Base class for Instagram parsers."""
    
    def get_saved_posts(self, limit: Optional[int] = None) -> Generator[Dict[str, Any], None, None]:
        """Extract saved posts from Instagram."""
        raise NotImplementedError
    
    def save_posts_to_db(self, db: SocialMediaDatabase, limit: Optional[int] = None,
                        force_update: bool = False, batch_size: int = 100) -> int:
        """Save Instagram posts to database with batch optimization."""
        saved_count = 0
        skipped_count = 0
        
        try:
            posts = list(self.get_saved_posts(limit))
            
            if not posts:
                logger.info("No posts to process")
                return 0
            
            # Batch check existing posts for better performance
            if not force_update:
                existing_shortcodes = self._batch_check_existing_posts(db, posts)
                logger.info(f"Found {len(existing_shortcodes)} existing posts to skip")
            else:
                existing_shortcodes = set()
            
            # Filter out existing posts
            posts_to_process = [post for post in posts if post['shortcode'] not in existing_shortcodes]
            skipped_count = len(posts) - len(posts_to_process)
            
            if not posts_to_process:
                logger.info(f"All {len(posts)} posts already exist. Skipped: {skipped_count}")
                return 0
                
            logger.info(f"Processing {len(posts_to_process)} new posts (skipping {skipped_count} existing)")
            
            # Process in batches for better performance
            with tqdm(total=len(posts_to_process), desc="Saving posts", unit="post") as pbar:
                for i in range(0, len(posts_to_process), batch_size):
                    batch = posts_to_process[i:i + batch_size]
                    batch_saved = self._save_batch_to_db(db, batch, pbar)
                    saved_count += batch_saved
                    
        except Exception as e:
            logger.error(f"Error during post saving: {str(e)}")
            logger.warning("Partial data may have been saved. Please check the database.")
        
        logger.info(f"Summary: Saved {saved_count} posts, Skipped {skipped_count} existing posts")
        return saved_count
    
    def _batch_check_existing_posts(self, db: SocialMediaDatabase, posts: List[Dict[str, Any]]) -> Set[str]:
        """Batch check which posts already exist in database."""
        existing_shortcodes = set()
        
        # Extract all shortcodes
        shortcodes = [post['shortcode'] for post in posts]
        
        # Batch query - much faster than individual checks
        with db as db_conn:
            placeholders = ','.join(['?'] * len(shortcodes))
            query = f"SELECT shortcode FROM instagram_posts WHERE shortcode IN ({placeholders})"
            db_conn._cursor.execute(query, shortcodes)
            existing_shortcodes = {row[0] for row in db_conn._cursor.fetchall()}
        
        return existing_shortcodes
    
    def _save_batch_to_db(self, db: SocialMediaDatabase, batch: List[Dict[str, Any]], pbar: tqdm) -> int:
        """Save a batch of posts to database."""
        saved_count = 0
        
        for post_data in batch:
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
                    pbar.set_postfix({'saved': saved_count})
                
            except Exception as e:
                logger.error(f"Error saving post {post_data['shortcode']}: {str(e)}")
                continue
            
            pbar.update(1)
        
        return saved_count

class InstaloaderParser(BaseInstagramParser):
    """Instagram parser using Instaloader."""
    
    def __init__(self, username: str, password: str, session_file: str = "instagram_session",
                 max_retries: Optional[int] = None, min_delay: Optional[float] = None, 
                 max_delay: Optional[float] = None, config_path: Optional[str] = None):
        """Initialize Instagram parser.
        
        Args:
            username: Instagram username
            password: Instagram password
            session_file: Name of session file for caching login
            max_retries: Maximum number of retry attempts for rate-limited requests. If None, uses config default.
            min_delay: Minimum delay between requests in seconds. If None, uses config default.
            max_delay: Maximum delay between requests in seconds. If None, uses config default.
            config_path: Path to configuration file. If None, uses default locations.
        """
        # Load configuration
        config = get_config(config_path)
        
        self._username = username
        self._password = password
        self._session_file = session_file
        
        # Use configuration with fallbacks
        self._max_retries = max_retries or config.get('api.max_retries', default=3)
        self._min_delay = min_delay or config.get('instagram.default_min_delay', default=5.0)
        self._max_delay = max_delay or config.get('instagram.default_max_delay', default=30.0)
        
        # Store configuration for other methods
        self._config = config
        
        # Initialize Instaloader with configured settings
        request_timeout = config.get('models.request_timeout', default=30)
        max_connection_attempts = config.get('api.max_retries', default=3)
        
        self._loader = instaloader.Instaloader(
            quiet=True,
            download_pictures=False,
            download_videos=False,
            download_video_thumbnails=False,
            download_geotags=False,
            download_comments=False,
            save_metadata=False,
            compress_json=False,
            max_connection_attempts=max_connection_attempts,
            request_timeout=request_timeout
        )
        
        self._login()
    
    def _login(self) -> None:
        """Login to Instagram, using cached session if available."""
        session_path = Path(self._session_file)
        
        try:
            if session_path.exists():
                self._loader.load_session_from_file(self._username, str(session_path))
                logger.info("Successfully loaded Instagram session from cache")
                # Verify session is still valid
                self._verify_session()
            else:
                self._perform_login()
        except Exception as e:
            logger.warning(f"Session error: {str(e)}. Attempting fresh login...")
            self._perform_login()
    
    def _verify_session(self) -> None:
        """Verify that the current session is valid."""
        try:
            # Try to access profile to verify session
            profile = instaloader.Profile.from_username(self._loader.context, self._username)
            delay_min = self._config.get('instagram.login_delay_min', default=1.0)
            delay_max = self._config.get('instagram.login_delay_max', default=2.0)
            time.sleep(random.uniform(delay_min, delay_max))
        except Exception:
            raise InstagramAPIError("Invalid session")
    
    def _perform_login(self) -> None:
        """Perform fresh login and save session."""
        try:
            logger.info("Logging in to Instagram...")
            self._loader.login(self._username, self._password)
            self._loader.save_session_to_file(self._session_file)
            logger.info("Successfully logged in and saved session")
        except Exception as e:
            logger.error(f"Failed to login to Instagram: {str(e)}")
            raise InstagramAPIError(f"Login failed: {str(e)}")
    
    @retry(
        retry=retry_if_exception_type((InstagramRateLimitError, instaloader.ConnectionException)),
        wait=wait_exponential(multiplier=5, min=5, max=60),
        stop=stop_after_attempt(5)
    )
    def _get_profile(self) -> instaloader.Profile:
        """Get Instagram profile with retry logic."""
        try:
            profile = instaloader.Profile.from_username(self._loader.context, self._username)
            time.sleep(random.uniform(2, 4))
            return profile
        except instaloader.ConnectionException as e:
            if any(x in str(e).lower() for x in ["429", "rate limit", "wait"]):
                logger.warning("Hit Instagram rate limit, will retry with exponential backoff...")
                raise InstagramRateLimitError(str(e))
            raise
    
    def _parse_post(self, post: instaloader.Post) -> Dict[str, Any]:
        """Parse Instagram post data."""
        try:
            # Extract hashtags and mentions from caption
            caption = post.caption or ""
            hashtags = list(post.caption_hashtags) if hasattr(post, 'caption_hashtags') else []
            mentions = list(post.caption_mentions) if hasattr(post, 'caption_mentions') else []
            
            return {
                'shortcode': post.shortcode,
                'owner_username': post.owner_username,
                'owner_id': str(post.owner_id),
                'caption': caption,
                'is_video': post.is_video,
                'url': post.url,
                'typename': post.typename,
                'likes': post.likes,
                'comments': post.comments,
                'created_at': post.date,
                'hashtags': hashtags,
                'mentions': mentions
            }
        except Exception as e:
            logger.error(f"Error parsing post data: {str(e)}")
            return None
    
    def _calculate_smart_delay(self, post_count: int, recent_errors: int = 0) -> float:
        """Calculate smart delay based on current conditions."""
        base_delay = self._min_delay
        
        # Adaptive delay based on progress (less aggressive than before)
        progress_factor = min(2.0, 1 + (post_count // 50) * 0.1)  # Slower progression
        
        # Error factor (increase delay if we're getting errors)
        error_factor = 1 + (recent_errors * 0.2)
        
        # Random factor for human-like behavior
        random_factor = 1 + random.uniform(-0.2, 0.4)
        
        calculated_delay = base_delay * progress_factor * error_factor * random_factor
        
        # Respect maximum delay
        return min(calculated_delay, self._max_delay)

    def get_saved_posts(self, limit: Optional[int] = None, db: Optional[SocialMediaDatabase] = None,
                       force_update: bool = False) -> Generator[Dict[str, Any], None, None]:
        """Extract saved posts from Instagram using Instaloader.
        
        Args:
            limit: Maximum number of posts to extract
            db: Optional database to check for existing posts
            force_update: If True, fetch all posts regardless of database state
        """
        post_count = 0
        total_posts = None
        pbar = None
        skipped_count = 0
        recent_errors = 0
        
        try:
            profile = self._get_profile()
            
            # Get total count of saved posts for progress bar
            try:
                saved_posts = list(profile.get_saved_posts())
                total_posts = len(saved_posts)
                desc = "Fetching posts (force update)" if force_update else "Fetching posts"
                logger.info(f"Found {total_posts} saved posts{' (force update)' if force_update else ''}")
                pbar = tqdm(total=total_posts, desc=desc, unit="post")
            except Exception as e:
                logger.warning(f"Could not get total post count: {str(e)}")
                saved_posts = profile.get_saved_posts()
            
            for post in saved_posts:
                if limit and post_count >= limit:
                    logger.info(f"Reached post limit of {limit}")
                    break
                
                try:
                    # Only check database if not forcing update
                    if db and not force_update:
                        exists = db.post_exists(post.shortcode)
                        if exists:
                            skipped_count += 1
                            if pbar:
                                pbar.set_postfix({
                                    'processed': post_count,
                                    'skipped': skipped_count,
                                    'mode': 'force update' if force_update else 'normal'
                                })
                                pbar.update(1)
                            continue
                    
                    # Smart delay calculation
                    delay = self._calculate_smart_delay(post_count, recent_errors)
                    
                    # Update progress message to show current delay
                    if pbar:
                        pbar.set_description(f"{'Updating' if force_update else 'Fetching'} posts (delay: {delay:.1f}s)")
                        pbar.set_postfix({
                            'processed': post_count,
                            'skipped': skipped_count,
                            'mode': 'force update' if force_update else 'normal'
                        })
                    time.sleep(delay)
                    
                    post_data = self._parse_post(post)
                    if post_data:
                        yield post_data
                        post_count += 1
                        recent_errors = max(0, recent_errors - 1)  # Decrease error count on success
                        if pbar:
                            pbar.update(1)
                    
                except Exception as e:
                    logger.error(f"Error processing post {post.shortcode}: {str(e)}")
                    recent_errors += 1
                    if pbar:
                        pbar.update(1)
                    continue
                
        except Exception as e:
            logger.error(f"Error fetching saved posts: {str(e)}")
            if "rate limit" in str(e).lower() or "wait" in str(e).lower():
                logger.warning("Instagram rate limit reached. Please wait before trying again.")
            raise
        finally:
            if pbar:
                pbar.close()
            if total_posts:
                status = "Force update" if force_update else "Normal fetch"
                logger.info(f"{status} completed. Processed: {post_count}, Skipped: {skipped_count}, Total: {total_posts}")

    def save_posts_to_db(self, db: SocialMediaDatabase, limit: Optional[int] = None,
                        force_update: bool = False, batch_size: int = 100) -> int:
        """Save Instagram posts to database with optimized batch processing."""
        saved_count = 0
        updated_count = 0
        
        try:
            # Pass database to get_saved_posts to enable early skipping
            posts = list(self.get_saved_posts(limit=limit, db=db, force_update=force_update))
            total_posts = len(posts)
            
            if total_posts == 0:
                logger.info("No posts to process")
                return 0
            
            action = "update" if force_update else "save"
            logger.info(f"Found {total_posts} posts to {action}")
            
            # Use optimized batch processing from base class
            if force_update:
                return super().save_posts_to_db(db, limit, force_update, batch_size)
            
            # Now show progress for database saving
            with tqdm(total=total_posts, desc=f"{'Updating' if force_update else 'Saving'} to database", unit="post") as pbar:
                for post_data in posts:
                    try:
                        # Only check if post exists when not forcing update
                        exists = False
                        if not force_update:
                            exists = db.post_exists(post_data['shortcode'])
                        
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
                            if exists:
                                updated_count += 1
                            else:
                                saved_count += 1
                            pbar.set_postfix({
                                'new': saved_count,
                                'updated': updated_count,
                                'total': total_posts
                            })
                        
                    except Exception as e:
                        logger.error(f"Error saving post {post_data['shortcode']}: {str(e)}")
                        continue
                    
                    pbar.update(1)
                
        except Exception as e:
            logger.error(f"Error during post saving: {str(e)}")
            logger.warning("Partial data may have been saved. Please check the database.")
        
        # Final summary
        if force_update:
            logger.info(f"Process completed. Updated: {updated_count}, New: {saved_count}, Total processed: {total_posts}")
        else:
            logger.info(f"Process completed. Saved: {saved_count}, Total new posts: {total_posts}")
        return saved_count + updated_count

class InstagramAPIParser(BaseInstagramParser):
    """Instagram parser using the Instagram Platform API."""
    
    def __init__(self, access_token: str, user_id: str):
        """Initialize Instagram Platform API parser.
        
        Args:
            access_token: Instagram Graph API access token
            user_id: Instagram Business Account ID
        """
        self._access_token = access_token
        self._user_id = user_id
        self._base_url = "https://graph.instagram.com/v12.0"
        
    def _make_request(self, endpoint: str, params: Dict[str, Any] = None) -> Dict[str, Any]:
        """Make a request to the Instagram Graph API."""
        if params is None:
            params = {}
        
        params['access_token'] = self._access_token
        
        try:
            response = requests.get(f"{self._base_url}/{endpoint}", params=params)
            response.raise_for_status()
            return response.json()
        except requests.exceptions.RequestException as e:
            raise InstagramAPIError(f"API request failed: {str(e)}")
    
    def get_saved_posts(self, limit: Optional[int] = None) -> Generator[Dict[str, Any], None, None]:
        """Extract posts using the Instagram Platform API."""
        try:
            params = {
                'fields': 'id,caption,media_type,media_url,permalink,thumbnail_url,'
                         'timestamp,username,children{media_url,media_type}',
                'limit': min(limit, 25) if limit else 25
            }
            
            endpoint = f"{self._user_id}/media"
            post_count = 0
            
            while True:
                response = self._make_request(endpoint, params)
                
                for post in response.get('data', []):
                    if limit and post_count >= limit:
                        return
                    
                    try:
                        post_data = self._parse_platform_api_post(post)
                        if post_data:
                            yield post_data
                            post_count += 1
                            
                    except Exception as e:
                        logger.error(f"Error processing post {post.get('id')}: {str(e)}")
                        continue
                    
                    # Basic rate limiting
                    time.sleep(random.uniform(1, 2))
                
                # Handle pagination
                next_page = response.get('paging', {}).get('next')
                if not next_page:
                    break
                    
                params = {'after': response['paging']['cursors']['after']}
                
        except Exception as e:
            logger.error(f"Error fetching posts: {str(e)}")
            raise
    
    def _parse_platform_api_post(self, post: Dict[str, Any]) -> Dict[str, Any]:
        """Parse Instagram Platform API post data."""
        try:
            # Extract hashtags and mentions from caption
            caption = post.get('caption', '')
            hashtags = [word[1:] for word in caption.split() if word.startswith('#')]
            mentions = [word[1:] for word in caption.split() if word.startswith('@')]
            
            return {
                'shortcode': post['id'],  # Platform API uses ID instead of shortcode
                'owner_username': post['username'],
                'owner_id': self._user_id,
                'caption': caption,
                'is_video': post['media_type'] == 'VIDEO',
                'url': post.get('media_url') or post.get('thumbnail_url'),
                'typename': post['media_type'],
                'likes': None,  # Not available in basic display API
                'comments': None,  # Not available in basic display API
                'created_at': datetime.strptime(post['timestamp'], '%Y-%m-%dT%H:%M:%S%z'),
                'hashtags': hashtags,
                'mentions': mentions
            }
        except Exception as e:
            logger.error(f"Error parsing post {post.get('id')}: {str(e)}")
            return None