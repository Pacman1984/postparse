# PostParse

A Python package for extracting and analyzing saved posts from social media platforms.

## Features

- Extract saved messages from Telegram
- Extract saved posts from Instagram
- Download and organize media files
- Analyze content using ML and LLM models
- Structured data storage with SQLite
- Content classification (recipes, tutorials, etc.)

## Installation

```bash
pip install postparse
```

## Project Structure

```
src/postparse/
├── core/                      # Core functionality
│   ├── database/             # Database core
│   └── config.py             # Global configuration
├── telegram/                 # Telegram module
│   ├── parser.py            # Main parser
│   ├── models/              # Data models
│   └── storage/             # DB operations
├── instagram/               # Instagram module
│   ├── parser.py           # Main parser
│   ├── models/             # Data models
│   └── storage/            # DB operations
└── analysis/               # Content analysis
    ├── classifiers/        # ML/LLM classifiers
    ├── models/            # Analysis models
    └── storage/           # Results storage
```

## Usage

### Telegram

```python
from postparse.telegram.parser import TelegramParser
from postparse.telegram.storage.models import TelegramDB

# Initialize parser and database
parser = TelegramParser(
    api_id="your_api_id",
    api_hash="your_api_hash",
    phone="+1234567890"
)
db = TelegramDB()

# Extract messages
async with parser:
    async for message in parser.get_saved_messages(limit=100):
        print(f"Saved message: {message.text}")
```

### Instagram

```python
from postparse.instagram.parser import InstagramParser
from postparse.instagram.storage.models import InstagramDB

# Initialize parser and database
parser = InstagramParser(username="your_username")
db = InstagramDB()

# Extract posts
for post in parser.get_saved_posts():
    print(f"Saved post: {post.caption}")
```

### Content Analysis

```python
from postparse.analysis.classifiers.llm import RecipeLLMClassifier
from postparse.analysis.storage.models import AnalysisDB

# Initialize classifier and database
classifier = RecipeLLMClassifier()
analysis_db = AnalysisDB()

# Analyze content
result = classifier.predict("Your content here")
print(f"Classification: {result.label} (confidence: {result.confidence})")

# Save results
analysis_db.save_result(
    content_id=123,
    content_source="telegram",
    classifier_name="recipe_llm",
    result=result
)
```

## Database Schema

### Telegram Tables
```sql
CREATE TABLE telegram_messages (
    message_id INTEGER,
    chat_id INTEGER,
    chat_title TEXT,
    sender_id INTEGER,
    sender_username TEXT,
    date TIMESTAMP,
    text TEXT,
    forward_from TEXT,
    forward_date TIMESTAMP,
    reply_to_message_id INTEGER,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (message_id, chat_id)
);

CREATE TABLE telegram_media (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    message_id INTEGER,
    chat_id INTEGER,
    file_id TEXT UNIQUE,
    file_type TEXT,
    file_path TEXT,
    downloaded BOOLEAN DEFAULT FALSE,
    download_path TEXT,
    FOREIGN KEY (message_id, chat_id) 
        REFERENCES telegram_messages(message_id, chat_id)
);
```

### Instagram Tables
```sql
CREATE TABLE instagram_posts (
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
    location TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    last_updated TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE instagram_media (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    post_id INTEGER,
    url TEXT,
    media_type TEXT,
    downloaded BOOLEAN DEFAULT FALSE,
    download_path TEXT,
    FOREIGN KEY(post_id) REFERENCES instagram_posts(id)
);
```

### Analysis Tables
```sql
CREATE TABLE content_analysis (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    content_id INTEGER NOT NULL,
    content_source TEXT NOT NULL,
    classifier_name TEXT NOT NULL,
    label TEXT NOT NULL,
    confidence REAL NOT NULL,
    analyzed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE analysis_details (
    analysis_id INTEGER NOT NULL,
    key TEXT NOT NULL,
    value TEXT NOT NULL,
    FOREIGN KEY(analysis_id) REFERENCES content_analysis(id),
    PRIMARY KEY(analysis_id, key)
);
```

## Development

### Running Tests
```bash
python -m pytest tests/
```

### Contributing
1. Fork the repository
2. Create a feature branch
3. Make your changes
4. Run tests
5. Submit a pull request

## License

MIT License
