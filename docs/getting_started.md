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
# DEPRECATED: Use [llm] section instead
zero_shot_model = "qwen2.5:72b-instruct"

[llm]
# LLM provider configuration for classification
default_provider = "lm_studio"  # or "ollama", "openai", "anthropic"
enable_fallback = true

# Example Ollama provider configuration
[[llm.providers]]
name = "ollama"
model = "qwen3:14b"
api_base = "http://localhost:11434"  # Configure your Ollama server here
timeout = 30
```

### Environment Variables

For sensitive credentials, create a `config/.env` file:

```bash
# API keys for LLM providers (used by classification system)
# OpenAI (or OpenAI-compatible endpoints like LM Studio)
OPENAI_API_KEY=your_key_here

# Anthropic Claude
ANTHROPIC_API_KEY=your_key_here

# Note: Ollama configuration is now in config.toml under [llm.providers]
# The legacy OLLAMA_IP and OLLAMA_PORT variables are no longer used
```

## Configuring LLM Providers

PostParse uses a unified LLM provider system for classification tasks. Configure providers in `config.toml` and switch between them using the `provider_name` parameter.

For detailed setup instructions, troubleshooting, and best practices, see the **[LLM Providers Guide](llm_providers.md)**.

### Quick Setup

**For local development:**
- Use **Ollama** or **LM Studio** (free, no API key)
- Run: `ollama run qwen3:14b` or start LM Studio server

**For production:**
- Use **OpenAI** or **Anthropic** (requires API key)
- Set environment variable: `export OPENAI_API_KEY='sk-...'`

### Supported Providers

- **Ollama**: Local LLM server (free, no API key needed)
- **LM Studio**: Local LLM with OpenAI-compatible API (free, requires dummy API key)
- **OpenAI**: GPT-4, GPT-3.5, etc. (requires API key)
- **Anthropic**: Claude models (requires API key)

### Configuration Structure

All LLM providers are configured in `config/config.toml` under the `[llm]` section:

```toml
[llm]
default_provider = "lm_studio"  # Which provider to use by default
enable_fallback = true          # Automatically try other providers on failure

# Each provider is defined with [[llm.providers]]
[[llm.providers]]
name = "ollama"
model = "qwen3:14b"
api_base = "http://192.168.1.100:11434"  # Your Ollama server URL
timeout = 30
temperature = 0.7

[[llm.providers]]
name = "openai"
model = "gpt-4o-mini"
timeout = 30
temperature = 0.7
# API key loaded from OPENAI_API_KEY environment variable
```

### Provider-Specific Setup

#### Ollama Setup

1. Install Ollama: [https://ollama.ai](https://ollama.ai)
2. Pull a model: `ollama pull qwen3:14b`
3. Start the server: `ollama serve`
4. Configure in `config.toml`:
   ```toml
   [[llm.providers]]
   name = "ollama"
   model = "qwen3:14b"
   api_base = "http://localhost:11434"  # Or your server IP:port
   ```

#### LM Studio Setup

1. Install LM Studio: [https://lmstudio.ai](https://lmstudio.ai)
2. Download a model in LM Studio
3. Start the local server (default: `http://localhost:1234`)
4. Set environment variable: `OPENAI_API_KEY=dummy`
5. Configure in `config.toml`:
   ```toml
   [[llm.providers]]
   name = "lm_studio"
   model = "qwen/qwen3-vl-8b"  # Model name from LM Studio
   api_base = "http://localhost:1234/v1"
   ```

#### OpenAI Setup

1. Get your API key from [https://platform.openai.com](https://platform.openai.com)
2. Set environment variable: `OPENAI_API_KEY=sk-...`
3. Configure in `config.toml`:
   ```toml
   [[llm.providers]]
   name = "openai"
   model = "gpt-4o-mini"  # or "gpt-4", "gpt-3.5-turbo", etc.
   ```

#### Anthropic Setup

1. Get your API key from [https://console.anthropic.com](https://console.anthropic.com)
2. Set environment variable: `ANTHROPIC_API_KEY=sk-ant-...`
3. Configure in `config.toml`:
   ```toml
   [[llm.providers]]
   name = "anthropic"
   model = "claude-3-5-sonnet-20241022"
   ```

### Using Different Providers in Code

```python
from postparse.services.analysis.classifiers import RecipeLLMClassifier

# Use default provider from config
classifier = RecipeLLMClassifier()

# Use a specific provider from [llm.providers]
classifier = RecipeLLMClassifier(provider_name='openai')     # Use OpenAI
classifier = RecipeLLMClassifier(provider_name='lm_studio')  # Use LM Studio
classifier = RecipeLLMClassifier(provider_name='ollama')     # Use Ollama

# Use default provider but override config path
classifier = RecipeLLMClassifier(config_path="custom/config.toml")
```

**Note**: The old `model_name` parameter has been replaced with `provider_name` for clarity. Use `provider_name` to select from configured providers in `[llm.providers]`.

### Migration from Legacy Ollama Configuration

If you previously used `OLLAMA_IP` and `OLLAMA_PORT` in `config/.env`:

**Old setup (no longer works):**
```bash
# config/.env
OLLAMA_IP=192.168.1.100
OLLAMA_PORT=11434
```

**New setup:**
```toml
# config/config.toml
[[llm.providers]]
name = "ollama"
model = "qwen3:14b"
api_base = "http://192.168.1.100:11434"
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
from postparse.services.analysis.classifiers import RecipeLLMClassifier

# Initialize database and classifier (uses default provider from config)
db = SocialMediaDatabase("my_data.db")
classifier = RecipeLLMClassifier()

# Get recent messages
messages = db.get_telegram_messages(limit=10)

# Classify each message and save to database
for msg in messages:
    if msg['content']:
        # Skip if already classified
        if db.has_classification(msg['id'], 'telegram', 'recipe_llm'):
            print(f"Message {msg['message_id']}: already classified")
            continue
        
        result = classifier.predict(msg['content'])
        
        # Save result to database
        db.save_classification_result(
            content_id=msg['id'],
            content_source='telegram',
            classifier_name='recipe_llm',
            label=result.label,
            confidence=result.confidence,
            details=result.details,
            llm_metadata=classifier.get_llm_metadata()
        )
        
        print(f"Message {msg['message_id']}: {result.label} (confidence: {result.confidence:.2f})")
        if result.details:
            print(f"  Details: {result.details}")

# Or use a specific provider
classifier = RecipeLLMClassifier(provider_name='openai')  # Use OpenAI GPT models
result = classifier.predict("My delicious pasta recipe...")
print(f"{result.label} - {result.details}")  # Structured output with recipe details
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

### LLM Provider Configuration

If classification fails, check your LLM provider setup:

**Configuration Issues:**
- Verify `config/config.toml` has the correct `[llm]` section
- Ensure `default_provider` matches a provider name in `[[llm.providers]]`
- Confirm `provider_name` (if used) matches a configured provider

**For Ollama:**
- Verify Ollama is running: `curl http://localhost:11434/api/tags`
- Check the `api_base` URL in the Ollama provider configuration
- Ensure the model is downloaded: `ollama pull qwen3:14b`

**For LM Studio:**
- Verify LM Studio server is running at `http://localhost:1234`
- Set `OPENAI_API_KEY=dummy` (any value works)
- Ensure model is loaded in LM Studio interface

**For OpenAI/Anthropic:**
- Set the appropriate API key: `export OPENAI_API_KEY='sk-...'` or `export ANTHROPIC_API_KEY='sk-ant-...'`
- Verify key is set: `echo $OPENAI_API_KEY`
- Check account has credits/billing set up

**Quick Test:**
```python
from postparse.services.analysis.classifiers import RecipeLLMClassifier

# Test default provider
classifier = RecipeLLMClassifier()
result = classifier.predict("Test recipe: mix flour and water")
print(f"Result: {result.label}")

# Test specific provider
classifier = RecipeLLMClassifier(provider_name='openai')
result = classifier.predict("Test recipe")
print(f"OpenAI result: {result.label}")
```

For detailed troubleshooting, see the **[LLM Providers Guide](llm_providers.md#troubleshooting)**.

