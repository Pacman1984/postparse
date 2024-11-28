# PostParse

A Python package for parsing and storing social media content from various platforms. Currently supports:
- Instagram posts (saved posts, with extensibility for other sources)
- Telegram saved messages

## Features

- Extract posts/messages from supported platforms
- Platform-specific SQLite database schemas
- Conservative rate limiting to protect accounts
- Hashtag and mention extraction
- Media URL tracking
- Comprehensive error handling
- Safe session management
- Extensive test coverage

## Installation

```bash
pip install -r requirements.txt
```

## Database Schema

The package uses SQLite with platform-specific tables and version tracking for schema migrations.

### Version Tracking

The database includes a version tracking table to manage schema changes:

#### schema_version
- `version`: INTEGER NOT NULL - Current database schema version

When the schema changes, the database will automatically migrate to the latest version.

### Instagram Tables

#### instagram_posts
- `id`: INTEGER PRIMARY KEY AUTOINCREMENT
- `shortcode`: TEXT NOT NULL UNIQUE - Post's unique identifier
- `post_url`: TEXT NOT NULL - Full URL to post (e.g., https://instagram.com/p/ABC123)
- `owner_username`: TEXT - Username of post owner
- `owner_id`: INTEGER - User ID of post owner
- `caption`: TEXT - Post caption/description
- `is_video`: BOOLEAN - Whether post contains video
- `media_url`: TEXT - URL to media content (image/video)
- `typename`: TEXT - Type of post (GraphImage, GraphVideo, etc)
- `likes`: INTEGER - Number of likes
- `comments`: INTEGER - Number of comments
- `is_saved`: BOOLEAN NOT NULL DEFAULT 0 - Whether this is a saved post
- `source`: TEXT NOT NULL DEFAULT 'saved' - Where this post was found (saved, profile, hashtag, etc)
- `created_at`: TIMESTAMP - When post was created on Instagram
- `fetched_at`: TIMESTAMP DEFAULT CURRENT_TIMESTAMP - When we fetched the post

#### instagram_hashtags
- `id`: INTEGER PRIMARY KEY AUTOINCREMENT
- `post_id`: INTEGER - Foreign key to instagram_posts(id)
- `hashtag`: TEXT NOT NULL
- UNIQUE constraint on (post_id, hashtag)

#### instagram_mentions
- `id`: INTEGER PRIMARY KEY AUTOINCREMENT
- `post_id`: INTEGER - Foreign key to instagram_posts(id)
- `username`: TEXT NOT NULL
- UNIQUE constraint on (post_id, username)

### Telegram Tables

#### telegram_messages
- `id`: INTEGER PRIMARY KEY AUTOINCREMENT
- `message_id`: INTEGER NOT NULL UNIQUE
- `chat_id`: INTEGER - Chat where message was posted
- `content`: TEXT - Message text content
- `content_type`: TEXT NOT NULL - Type of content (text, image, video, etc)
- `media_urls`: TEXT - JSON array of media URLs
- `views`: INTEGER - Number of views
- `forwards`: INTEGER - Number of forwards
- `reply_to_msg_id`: INTEGER - ID of message being replied to
- `created_at`: TIMESTAMP - When message was created
- `saved_at`: TIMESTAMP DEFAULT CURRENT_TIMESTAMP - When we saved it

#### telegram_hashtags
- `id`: INTEGER PRIMARY KEY AUTOINCREMENT
- `message_id`: INTEGER - Foreign key to telegram_messages(id)
- `hashtag`: TEXT NOT NULL
- UNIQUE constraint on (message_id, hashtag)

## Usage

### First Time Setup

When using the package for the first time or after updates, the database will automatically:
1. Create necessary tables if they don't exist
2. Migrate existing database to latest schema version
3. Preserve data when possible during migrations

```python
from postparse.data.database import SocialMediaDatabase

# Initialize database (will create or migrate as needed)
db = SocialMediaDatabase("social_media.db")
```

### Database Migration

If you encounter schema-related errors (e.g., missing columns), you can force a database reset:

1. Delete the existing database file:
```python
import os
if os.path.exists("social_media.db"):
    os.remove("social_media.db")
```

2. Create a new database with the latest schema:
```python
db = SocialMediaDatabase("social_media.db")
```

### Instagram

```python
from postparse.instagram.instagram_parser import InstagramParser
from postparse.data.database import SocialMediaDatabase

# Initialize database
db = SocialMediaDatabase("social_media.db")

# Initialize Instagram parser with safe settings
parser = InstagramParser(
    username="your_username",
    password="your_password",
    session_file="instagram_session"  # Optional: for caching login
)

# Save saved posts with conservative limits
saved_count = parser.save_posts_to_db(
    db=db,
    limit=10,  # Start with small batch
    max_requests_per_session=20,  # Limit API requests
    is_saved=True,  # Mark as saved post
    source='saved'  # Indicate source
)
print(f"Saved {saved_count} posts")

# Retrieve a specific post
post = db.get_instagram_post(shortcode="ABC123")
if post:
    print(f"Post URL: {post['post_url']}")  # https://instagram.com/p/ABC123
    print(f"Caption: {post['caption']}")
    print(f"Source: {post['source']}")  # 'saved'
    print(f"Hashtags: {post['hashtags']}")
    print(f"Mentions: {post['mentions']}")
```

### Telegram

```python
from postparse.telegram.telegram_parser import save_telegram_messages

# Get API credentials from https://my.telegram.org
api_id = "your_api_id"
api_hash = "your_api_hash"

# Save messages with conservative limits
saved_count = save_telegram_messages(
    api_id=api_id,
    api_hash=api_hash,
    db_path="social_media.db",
    session_file="telegram_session",  # Optional: for caching login
    limit=10,  # Start with small batch
    max_requests_per_session=20  # Limit API requests
)
print(f"Saved {saved_count} messages")

# Retrieve a specific message
message = db.get_telegram_message(message_id=12345)
if message:
    print(f"Content: {message['content']}")
    print(f"Hashtags: {message['hashtags']}")
```

## Safety Features

The package implements several safety measures to protect your accounts:

### Rate Limiting
- Minimum 3-5 seconds between requests
- Extra 15-20 seconds delay every 10 requests
- Longer 30-45 seconds delay every 50 requests
- Random delays to avoid patterns
- Maximum requests per session (default: 20)

### Error Handling
- Graceful handling of missing attributes
- Retries with exponential backoff
- Session caching to reduce authentication requests
- Detailed error messages for debugging
- Safe transaction handling for database operations

### Data Integrity
- Unique constraints to prevent duplicates
- Foreign key relationships for data consistency
- Proper data type handling
- Transaction-based saves
- Automatic timestamps

## Development

### Running Tests

```bash
pytest tests/
```

### Code Style

The project follows PEP 8 guidelines. Format code using:

```bash
black src/ tests/
isort src/ tests/
```

### Database Versioning

The database schema uses versioning to manage changes:
1. Current version is stored in `SocialMediaDatabase.CURRENT_VERSION`
2. Schema changes increment the version number
3. Migrations are handled automatically
4. Version history is maintained for compatibility

When making schema changes:
1. Increment `CURRENT_VERSION` in database.py
2. Update the migration logic in `__migrate_database()`
3. Document changes in commit messages
4. Update tests to reflect schema changes

## Database Queries

Here are some useful SQL queries for analyzing your data:

### Instagram Analytics
```sql
-- Get saved posts with most likes
SELECT post_url, caption, likes, created_at
FROM instagram_posts
WHERE is_saved = 1
ORDER BY likes DESC
LIMIT 10;

-- Get posts by source
SELECT source, COUNT(*) as count
FROM instagram_posts
GROUP BY source
ORDER BY count DESC;

-- Get most used hashtags in saved posts
SELECT h.hashtag, COUNT(*) as count
FROM instagram_hashtags h
JOIN instagram_posts p ON h.post_id = p.id
WHERE p.is_saved = 1
GROUP BY h.hashtag
ORDER BY count DESC
LIMIT 10;

-- Get posts by specific user with save status
SELECT post_url, caption, is_saved, source, created_at
FROM instagram_posts
WHERE owner_username = 'specific_user'
ORDER BY created_at DESC;

-- Get all video posts
SELECT post_url, caption, likes, source
FROM instagram_posts
WHERE is_video = 1
ORDER BY created_at DESC;

-- Get save rate by user
SELECT 
    owner_username,
    COUNT(*) as total_posts,
    SUM(CASE WHEN is_saved = 1 THEN 1 ELSE 0 END) as saved_posts,
    ROUND(CAST(SUM(CASE WHEN is_saved = 1 THEN 1 ELSE 0 END) AS FLOAT) / COUNT(*) * 100, 2) as save_rate
FROM instagram_posts
GROUP BY owner_username
HAVING total_posts > 5
ORDER BY save_rate DESC;
```

### Telegram Analytics
```sql
-- Get most forwarded messages
SELECT message_id, content, forwards
FROM telegram_messages
ORDER BY forwards DESC
LIMIT 10;

-- Get messages by type
SELECT content_type, COUNT(*) as count
FROM telegram_messages
GROUP BY content_type;

-- Get messages with media
SELECT *
FROM telegram_messages
WHERE media_urls IS NOT NULL;
```

## License

MIT License - see LICENSE file for details.

## File Structure

The package maintains a clean and organized file structure for cache files and downloaded media:

```
data/
├── cache/                 # Session and cache files
│   ├── instagram_session  # Instagram login session
│   └── telegram_session  # Telegram login session
└── downloads/            # Downloaded media files
    ├── instagram/        # Instagram media
    │   └── [username]/   # Per-user directories
    │       └── saved/    # Saved posts
    │           └── YYYY-MM-DD_shortcode/  # Post media and metadata
    └── telegram/         # Telegram media (organized by message creation date)
        └── YYYY/         # Year from message date
            └── MM/       # Month from message date (01-12)
                └── DD/   # Day from message date (01-31)
                    └── [message_id]_[filename]  # Media files
```

### Cache Directory
- `data/cache/`: Stores session files and other cache data
  - `instagram_session`: Instagram login session (managed by Instaloader)
  - `telegram_session`: Telegram login session (managed by Telethon)

### Downloads Directory
- `data/downloads/`: Root directory for all downloaded media
  - **Instagram**:
    - Organized by username and post type
    - Each post gets its own directory with timestamp and shortcode
    - Media files retain original names when possible
  - **Telegram**:
    - Organized by message creation date (not download date)
    - Directory structure reflects when messages were sent
    - Files prefixed with message ID for uniqueness
    - Original filenames preserved when possible
    - Automatic file type detection for photos/documents

### File Naming
- **Instagram Posts**: `[YYYY-MM-DD]_[shortcode]/[media_files]`
- **Telegram Messages**: `[message_id]_[original_filename]`
  - Photos without names: `[message_id]_media_[message_timestamp].jpg`
  - Documents: `[message_id]_[cleaned_original_name]`
  - All files stored in directories matching message creation date

### Path Configuration
You can customize the storage locations when initializing the parsers:

```python
# Custom paths for Instagram
instagram_parser = InstagramParser(
    username="your_username",
    password="your_password",
    session_file="instagram_session",  # Just the filename
    cache_dir="path/to/cache",         # Custom cache directory
    downloads_dir="path/to/downloads"   # Custom downloads directory
)

# Custom paths for Telegram
saved_count = save_telegram_messages(
    api_id="your_api_id",
    api_hash="your_api_hash",
    phone="your_phone",
    session_file="telegram_session",    # Just the filename
    cache_dir="path/to/cache",          # Custom cache directory
    downloads_dir="path/to/downloads",   # Custom downloads directory
    limit=10
)
```

### File Cleaning
- All filenames are cleaned to ensure compatibility:
  - Only alphanumeric characters, dots, underscores, and hyphens allowed
  - Spaces preserved but controlled
  - Special characters removed
  - Unique identifiers (message_id, shortcode) prevent conflicts

### Directory Setup

The package will automatically create the necessary directories, but you can also set them up manually:

```python
from pathlib import Path

# Create base directories
Path("data/cache").mkdir(parents=True, exist_ok=True)
Path("data/downloads/instagram").mkdir(parents=True, exist_ok=True)
Path("data/downloads/telegram").mkdir(parents=True, exist_ok=True)
```

### Default Paths
If not specified, the package uses these default paths:
- Cache files: `./data/cache/`
  - Instagram session: `./data/cache/instagram_session`
  - Telegram session: `./data/cache/telegram_session`
- Downloads:
  - Instagram media: `./data/downloads/instagram/`
  - Telegram media: `./data/downloads/telegram/`

### Storage Considerations
- **Session Files**: Small (~KB), but important for maintaining login state
- **Media Files**: Can grow large depending on content
  - Photos: ~100KB-5MB each
  - Videos: ~1MB-100MB each
  - Documents: Varies significantly
- Consider periodic cleanup of old media files if storage is a concern
- Session files should be preserved to avoid frequent re-authentication

### Backup Recommendations
- **Always Backup**:
  - Session files (to avoid re-authentication)
  - Database file (contains all metadata)
- **Optional Backup**:
  - Downloaded media (can be re-downloaded if needed)
  - Consider backing up specific media based on importance

### Git Configuration

#### Recommended .gitignore
Add these entries to your .gitignore to avoid committing sensitive data:

```gitignore
# Cache and session files
data/cache/
*.session
*.session-journal

# Downloaded media
data/downloads/

# Database
*.db
*.db-journal

# Environment variables
.env

# Python cache
__pycache__/
*.py[cod]
*$py.class
.Python
*.so
```

#### Environment Variables
Store sensitive information in a `.env` file:

```env
# Instagram credentials
INSTAGRAM_USERNAME=your_username
INSTAGRAM_PASSWORD=your_password

# Telegram credentials (from https://my.telegram.org)
TELEGRAM_API_ID=your_api_id
TELEGRAM_API_HASH=your_api_hash
TELEGRAM_PHONE=your_phone_number  # In international format (e.g., +1234567890)
```
