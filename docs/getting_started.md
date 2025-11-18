# Getting Started

This guide will help you install PostParse and run your first data extraction.

## Installation

### Using UV (Recommended)

First, install UV if you haven't already:

```bash
# On macOS and Linux:
curl -LsSf https://astral.sh/uv/install.sh | sh

# On Windows:
powershell -c "irm https://astral.sh/uv/install.ps1 | iex"
```

Then install PostParse:

```bash
uv pip install postparse
```

### From Source

```bash
git clone https://github.com/sebpachl/postparse.git
cd postparse

# Create virtual environment and install
uv venv
uv sync

# Install with dev dependencies
uv sync --extra dev
```

### Alternative: Using pip (Not Recommended)

```bash
pip install postparse
```

## Requirements

- Python 3.10 or higher (required for modern LangChain, better type hints, and improved async support)
- SQLite (included with Python)
- UV package manager (recommended for development)
- For Telegram: API credentials from [my.telegram.org](https://my.telegram.org)
- For Instagram: Valid Instagram account credentials
- For LLM classification: Ollama server (optional)

## Working with UV

UV is a fast, all-in-one Python package manager that simplifies dependency management:

**Add dependencies:**
```bash
uv add <package>
```

**Run scripts:**
```bash
uv run python script.py
```

**Activate virtual environment:**
```bash
# On Unix/macOS:
source .venv/bin/activate

# On Windows:
.venv\Scripts\activate
```

**Update dependencies:**
```bash
uv lock --upgrade
```

## Configuration

PostParse uses a centralized configuration system. All configuration files should be placed in the `config/` directory at your project root.

### Basic Configuration

Create a `config/config.toml` file:

```toml
[database]
default_db_path = "social_media.db"

[paths]
cache_dir = "data/cache"
telegram_downloads_dir = "data/downloads/telegram"
instagram_downloads_dir = "data/downloads/instagram"

[telegram]
connection_retries = 3
retry_delay = 1
auto_reconnect = true
request_delay_base = 2.0

[instagram]
default_min_delay = 5.0
default_max_delay = 30.0

[models]
zero_shot_model = "qwen2.5:72b-instruct"
```

### Environment Variables

For sensitive credentials, create a `config/.env` file:

```bash
# Ollama server configuration (for classification)
OLLAMA_IP=192.168.1.100
OLLAMA_PORT=11434

# Optional: Override model selection
ZERO_SHOT_MODEL=qwen2.5:72b-instruct
```

## Your First Data Extraction

### Example 1: Extract Telegram Messages

```python
import asyncio
from postparse.services.parsers.telegram.telegram_parser import TelegramParser, save_telegram_messages
from postparse.core.data.database import SocialMediaDatabase

# Option 1: Using the helper function (handles async automatically)
saved_count = save_telegram_messages(
    api_id="your_api_id",
    api_hash="your_api_hash",
    phone="+1234567890",
    limit=50  # Extract 50 most recent messages
)
print(f"Saved {saved_count} messages")

# Option 2: Using async/await directly (for more control)
async def extract_messages():
    db = SocialMediaDatabase("my_data.db")
    
    async with TelegramParser(
        api_id="your_api_id",
        api_hash="your_api_hash",
        phone="+1234567890"
    ) as parser:
        count = await parser.save_messages_to_db(db, limit=50)
        print(f"Saved {count} messages")

# Run the async function
asyncio.run(extract_messages())
```

### Example 2: Extract Instagram Posts

```python
from postparse.services.parsers.instagram.instagram_parser import InstaloaderParser
from postparse.core.data.database import SocialMediaDatabase

# Initialize database
db = SocialMediaDatabase("my_data.db")

# Initialize Instagram parser
parser = InstaloaderParser(
    username="your_username",
    password="your_password"
)

# Extract and save posts
saved_count = parser.save_posts_to_db(db, limit=20)
print(f"Saved {saved_count} posts")
```

### Example 3: Classify Content

```python
from postparse.core.data.database import SocialMediaDatabase
from postparse.services.analysis.classifiers.recipe_classifier import RecipeClassifier

# Initialize database and classifier
db = SocialMediaDatabase("my_data.db")
classifier = RecipeClassifier()

# Get recent messages
messages = db.get_telegram_messages(limit=10)

# Classify each message
for msg in messages:
    if msg['content']:
        result = classifier.predict(msg['content'])
        print(f"Message {msg['message_id']}: {result}")
```

## Inspecting Your Data

Once you've extracted data, you can query it using the database methods:

```python
from postparse.core.data.database import SocialMediaDatabase

db = SocialMediaDatabase("my_data.db")

# Get all Instagram posts
posts = db.get_instagram_posts(limit=10)
for post in posts:
    print(f"{post['owner_username']}: {post['caption'][:50]}...")

# Get all Telegram messages
messages = db.get_telegram_messages(limit=10)
for msg in messages:
    print(f"Message {msg['message_id']}: {msg['content'][:50]}...")

# Search by hashtag
recipe_posts = db.get_posts_by_hashtag("recipe")
print(f"Found {len(recipe_posts)} posts with #recipe")
```

## Next Steps

Now that you have the basics working:

1. **Explore the [Cookbook](cookbook.md)** for task-specific examples
2. **Read the [API Reference](api_reference.md)** for detailed documentation
3. **Customize your configuration** in `config/config.toml` for your needs
4. **Set up automated extraction** using cron jobs or scheduled tasks

## Common Issues

### Telegram Authentication

If you encounter authentication issues:
- Ensure your API credentials are correct from [my.telegram.org](https://my.telegram.org)
- Check that your phone number includes the country code (e.g., `+1234567890`)
- The first run will prompt for a verification code sent to your Telegram app

### Instagram Rate Limiting

Instagram has strict rate limits. If you hit them:
- Increase the delay values in `config/config.toml`
- Reduce the number of posts fetched per session
- Wait several hours before retrying

### Ollama Connection

If classification fails:
- Verify Ollama is running: `curl http://your-ollama-ip:11434/api/tags`
- Check `OLLAMA_IP` and `OLLAMA_PORT` in `config/.env`
- Ensure the model is downloaded: `ollama pull qwen2.5:72b-instruct`

