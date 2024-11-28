import sqlite3
from pathlib import Path
from datetime import datetime
import pickle
from typing import List, Any, Optional

class InstagramDB:
    """Database handler for Instagram-related data."""
    
    def __init__(self, db_dir: str = "data"):
        """Initialize the Instagram database connection.
        
        Args:
            db_dir (str): Directory where the database file will be stored.
        """
        # Create database directory if it doesn't exist
        self.db_dir = Path(db_dir)
        self.db_dir.mkdir(parents=True, exist_ok=True)
        
        # Initialize database
        self.init_db()
    
    def init_db(self) -> None:
        """Initialize the database with all necessary tables."""
        conn = self._get_connection()
        cursor = conn.cursor()

        # Create instagram posts table
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS instagram_posts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                shortcode TEXT UNIQUE,
                owner_username TEXT,
                date_utc TIMESTAMP,
                caption TEXT,
                likes INTEGER,
                comments INTEGER,
                is_video BOOLEAN,
                media_count INTEGER,
                is_saved_post BOOLEAN DEFAULT FALSE,
                taxonomy TEXT,
                binary_data BLOB,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                last_updated TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        
        # Create instagram metadata table for storing additional attributes
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS instagram_metadata (
                post_id INTEGER,
                key TEXT,
                value TEXT,
                FOREIGN KEY(post_id) REFERENCES instagram_posts(id),
                PRIMARY KEY(post_id, key)
            )
        ''')

        conn.commit()
        conn.close()
    
    def _get_connection(self) -> sqlite3.Connection:
        """Get a database connection.
        
        Returns:
            sqlite3.Connection: Database connection object
        """
        return sqlite3.connect(self.db_dir / "social_media.db")
    
    def save_post(self, post: Any, taxonomy: str = "saved_posts") -> None:
        """Save an Instagram post to the database.
        
        Args:
            post: Instaloader Post object
            taxonomy (str): Post classification/category
        """
        conn = self._get_connection()
        cursor = conn.cursor()
        
        try:
            # Serialize post object
            binary_data = pickle.dumps(post)
            
            # Insert or update post data
            cursor.execute('''
                INSERT INTO instagram_posts (
                    shortcode, owner_username, date_utc, caption, 
                    likes, comments, is_video, media_count, is_saved_post,
                    binary_data, taxonomy
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(shortcode) DO UPDATE SET
                    is_saved_post = TRUE,
                    taxonomy = CASE 
                        WHEN taxonomy IS NULL THEN ?
                        WHEN taxonomy NOT LIKE ? THEN taxonomy || ','|| ?
                        ELSE taxonomy
                    END,
                    last_updated = CURRENT_TIMESTAMP
            ''', (
                post.shortcode,
                post.owner_username,
                post.date_utc,
                post.caption if post.caption is not None else "",
                post.likes,
                post.comments,
                post.is_video,
                post.mediacount if hasattr(post, 'mediacount') else 1,
                True,  # is_saved_post
                binary_data,
                taxonomy,
                taxonomy,
                f"%{taxonomy}%",
                taxonomy
            ))
            
            # Get the post id
            post_id = cursor.lastrowid or cursor.execute(
                'SELECT id FROM instagram_posts WHERE shortcode = ?', 
                (post.shortcode,)
            ).fetchone()[0]
            
            # Store additional metadata if location exists
            if hasattr(post, 'location') and post.location:
                cursor.execute('''
                    INSERT OR REPLACE INTO instagram_metadata (post_id, key, value)
                    VALUES (?, ?, ?)
                ''', (post_id, 'location', str(post.location)))
            
            conn.commit()
            
        finally:
            conn.close()
    
    def get_posts(self, taxonomy: Optional[str] = None) -> List[Any]:
        """Retrieve posts from the database.
        
        Args:
            taxonomy (str, optional): Filter posts by taxonomy
            
        Returns:
            List[Any]: List of deserialized Instagram post objects
        """
        conn = self._get_connection()
        cursor = conn.cursor()
        
        try:
            if taxonomy:
                cursor.execute('''
                    SELECT binary_data 
                    FROM instagram_posts 
                    WHERE taxonomy LIKE ?
                    ORDER BY date_utc DESC
                ''', (f'%{taxonomy}%',))
            else:
                cursor.execute('''
                    SELECT binary_data 
                    FROM instagram_posts 
                    ORDER BY date_utc DESC
                ''')
            
            return [pickle.loads(row[0]) for row in cursor.fetchall()]
            
        finally:
            conn.close() 