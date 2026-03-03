# PostParse

A Python package for extracting and analyzing saved posts from social media platforms.

## Features

- Extract saved messages from Telegram
- Extract saved posts from Instagram
- Download and organize media files
- Analyze content using ML and LLM models
- Structured data storage with SQLite
- Content classification (recipes, tutorials, etc.)
- **Multi-Class Classification**: Classify text into custom categories with dynamic class definitions (config or runtime)

## Documentation

📚 **[Read the full documentation](docs/index.md)**

- **[Quickstart](docs/02-quickstart.md)** — Install and first commands
- **[Examples](docs/08-examples/recipes.md)** — Copy-pastable recipes
- **[API Endpoints](docs/06-api/endpoints.md)** — REST API
- **[Python API](docs/06-api/python-reference.md)** — Database, parsers, classifiers

## Quick Start

### Installation

**Using UV (Recommended):**

```bash
uv pip install postparse
```

**Or install from source:**

```bash
git clone https://github.com/sebpachl/postparse.git
cd postparse
uv sync
```

## CLI Usage

PostParse provides a beautiful command-line interface built with Click and Rich for easy access to all features.

### Quick Start

After installation, the `postparse` command is available:

```bash
# Show help and available commands
postparse --help

# Check database and for new content
postparse stats
postparse check

# Extract Telegram messages (from Saved Messages folder)
postparse extract telegram --api-id 12345 --api-hash abc123

# Classify text
postparse classify text "Mix flour and water to make dough"

# Start the API server
postparse serve --port 8080
```

### Available Commands

- **`stats`** - View database statistics
  
- **`check`** - Check for new content (fast preview, no download)
  - `telegram` - Check Telegram for new messages
  - `instagram` - Check Instagram for new posts
  - `all` - Check both platforms (default)

- **`extract`** - Extract data from social media platforms
  - `telegram` - Extract from Telegram Saved Messages
  - `instagram` - Extract Instagram saved posts
  
- **`classify`** - Classify content as recipe/not recipe
  - `single` - Classify a single text (supports stdin)
  - `batch` - Classify multiple items from database
  
- **`search`** - Search stored posts and messages
  - `posts` - Search Instagram posts with filters
  - `messages` - Search Telegram messages with filters
  
- **`serve`** - Start the FastAPI server
  
- **`db`** - Database operations and statistics
  - `stats` - Show database statistics
  - `export` - Export database to JSON/CSV
  
- **`config`** - Configuration management
  - `show` - Display current configuration
  - `validate` - Validate configuration file

### Example Workflows

**Extract and classify Telegram messages:**

```bash
# Check for new content first
postparse check telegram

# Extract messages (from Saved Messages folder)
postparse extract telegram --api-id $TELEGRAM_API_ID --api-hash $TELEGRAM_API_HASH --limit 100

# Classify them
postparse classify db --source telegram --limit 100

# Search for recipes
postparse search messages --hashtag recipe
```

**Export database:**

```bash
# Export all data to JSON
postparse db export data.json

# Export only posts to CSV
postparse db export posts.csv --format csv --source posts --limit 1000
```

**Start API server for frontend:**

```bash
# Development mode with auto-reload
postparse serve --reload --port 8080

# Production mode with multiple workers
postparse serve --workers 4 --log-level info
```

### Getting Help

Get help for any command using the `--help` flag:

```bash
postparse extract telegram --help
postparse classify db --help
postparse search posts --help
```

For CLI details, see **[05-usage/basic](docs/05-usage/basic.md)** and **[06-api/endpoints](docs/06-api/endpoints.md)**.

## Quick Example

```python
from backend.postparse.services.parsers.telegram.telegram_parser import save_telegram_messages
from backend.postparse.core.data.database import SocialMediaDatabase
from backend.postparse.services.analysis.classifiers import RecipeLLMClassifier

# Extract Telegram messages
count = save_telegram_messages(
    api_id="your_api_id",
    api_hash="your_api_hash",
    phone="+1234567890",
    limit=100
)

# Classify content with LangChain + LiteLLM
db = SocialMediaDatabase()
classifier = RecipeLLMClassifier()  # Supports Ollama, LM Studio, OpenAI, etc.

messages = db.get_telegram_messages(limit=10)
for msg in messages:
    if msg['content']:
        result = classifier.predict(msg['content'])
        print(f"Message {msg['message_id']}: {result.label} ({result.confidence:.2f})")
        print(f"  Details: {result.details}")
```

For more examples, see **[08-examples/recipes](docs/08-examples/recipes.md)**.

### Multi-Class Classification

Classify text into custom categories:

```python
from backend.postparse.services.analysis.classifiers import MultiClassLLMClassifier

# Define your classes
classes = {
    "recipe": "Cooking instructions or ingredients",
    "tech_news": "Technology news or product announcements",
    "sports": "Sports news, scores, or athlete updates"
}

classifier = MultiClassLLMClassifier(classes=classes)
result = classifier.predict("Apple announces new iPhone 16")
print(f"Category: {result.label} (confidence: {result.confidence:.2f})")
# Output: Category: tech_news (confidence: 0.92)
```

Or via CLI:

```bash
postparse classify multi "Apple announces iPhone 16" \
  --classes '{"recipe": "Cooking", "tech_news": "Tech news", "sports": "Sports"}'
```

Or via API:

```bash
curl -X POST "http://localhost:8000/api/v1/classify/multi" \
  -H "Content-Type: application/json" \
  -d '{
    "text": "Apple announces iPhone 16",
    "classes": {
      "recipe": "Cooking instructions",
      "tech_news": "Technology news",
      "sports": "Sports news"
    }
  }'
```

For more details, see **[07-configuration](docs/07-configuration.md)**.

## API Server

PostParse now includes a REST API built with FastAPI for programmatic access to all features.

### Starting the API Server

```bash
# Development mode (with auto-reload)
uv run python -m backend.postparse.api.main

# Or using uvicorn directly
uv run uvicorn backend.postparse.api.main:app --reload --host 0.0.0.0 --port 8000
```

### API Documentation

Once the server is running, access the interactive API documentation:

- **Swagger UI**: http://localhost:8000/docs
- **ReDoc**: http://localhost:8000/redoc
- **OpenAPI JSON**: http://localhost:8000/openapi.json

### API Endpoints

- **Telegram**: `/api/v1/telegram/extract`, `/api/v1/telegram/messages`
- **Instagram**: `/api/v1/instagram/extract`, `/api/v1/instagram/posts`
- **Classification**: `/api/v1/classify/recipe`, `/api/v1/classify/batch`
- **Multi-Class**: `/api/v1/classify/multi`, `/api/v1/classify/multi/batch`
- **Search**: `/api/v1/search/posts`, `/api/v1/search/messages`
- **Jobs**: `/api/v1/jobs/{job_id}` (unified job status for all platforms)
- **Health**: `/health`, `/health/ready`, `/metrics`

### WebSocket Endpoints for Real-Time Progress

PostParse provides WebSocket endpoints for receiving live extraction job progress updates.

**Unified Endpoint (Recommended):**

- `ws://localhost:8000/api/v1/jobs/ws/progress/{job_id}` - Works for all platforms (Telegram, Instagram)

**Platform-Specific Endpoints (Backward Compatibility):**

- `ws://localhost:8000/api/v1/telegram/ws/progress/{job_id}` - Telegram jobs only
- `ws://localhost:8000/api/v1/instagram/ws/progress/{job_id}` - Instagram jobs only

All WebSocket endpoints provide identical functionality and message format. Use the unified endpoint for new integrations.

### Example API Usage

```python
import requests

# Classify text via API
response = requests.post(
    "http://localhost:8000/api/v1/classify/recipe",
    json={
        "text": "Boil pasta, add tomato sauce and basil",
        "classifier_type": "llm",
        "provider_name": "lm_studio"
    }
)
result = response.json()
print(f"Classification: {result['label']} ({result['confidence']:.2f})")
```

For more API examples, see **[06-api/endpoints](docs/06-api/endpoints.md)**.

## Extraction API Usage

### Telegram Message Extraction

**Start Extraction Job:**

```bash
curl -X POST http://localhost:8000/api/v1/telegram/extract \
  -H "Content-Type: application/json" \
  -d '{
    "api_id": "12345678",
    "api_hash": "0123456789abcdef0123456789abcdef",
    "phone": "+1234567890",
    "limit": 100
  }'
```

Response:

```json
{
  "job_id": "550e8400-e29b-41d4-a716-446655440000",
  "status": "pending",
  "message_count": 0,
  "estimated_time": 60
}
```

**Check Job Status:**

```bash
curl http://localhost:8000/api/v1/telegram/jobs/550e8400-e29b-41d4-a716-446655440000
```

**Real-time Progress (WebSocket):**

Use the unified WebSocket endpoint for any job type:

```javascript
// Recommended: Unified endpoint (works for all platforms)
const ws = new WebSocket('ws://localhost:8000/api/v1/jobs/ws/progress/550e8400-e29b-41d4-a716-446655440000');

ws.onmessage = (event) => {
  const progress = JSON.parse(event.data);
  console.log(`Progress: ${progress.progress}% - ${progress.messages_processed} messages`);
};

// Alternative: Platform-specific endpoint (backward compatibility)
// const ws = new WebSocket('ws://localhost:8000/api/v1/telegram/ws/progress/550e8400-e29b-41d4-a716-446655440000');
```

### Instagram Post Extraction

> **Note:** Currently, only Instaloader-based extraction is supported (`use_api=false`). Instagram Platform API extraction (`use_api=true`) is not yet implemented.

**Start Extraction Job:**

```bash
curl -X POST http://localhost:8000/api/v1/instagram/extract \
  -H "Content-Type: application/json" \
  -d '{
    "username": "cooking_profile",
    "password": "secret123",
    "limit": 50,
    "use_api": false
  }'
```

**WebSocket Progress:**

```javascript
// Recommended: Unified endpoint (works for all platforms)
const ws = new WebSocket('ws://localhost:8000/api/v1/jobs/ws/progress/{job_id}');

// Alternative: Platform-specific endpoint (backward compatibility)
// const ws = new WebSocket('ws://localhost:8000/api/v1/instagram/ws/progress/{job_id}');

ws.onmessage = (event) => {
  const progress = JSON.parse(event.data);
  console.log(`Progress: ${progress.progress}% - ${progress.messages_processed} posts`);
};
```

### Rate Limiting

The API enforces rate limits to prevent abuse:

- **Default:** 60 requests per minute per IP
- **Burst:** Up to 10 additional requests
- **Response:** 429 Too Many Requests when limit exceeded

Health endpoints (`/health`, `/docs`) are excluded from rate limiting.

### Authentication

For Telegram extraction, you need:

1. API credentials from https://my.telegram.org
2. Phone number in international format
3. Existing session file OR interactive authentication

**First-time Setup (Interactive):**

```python
from backend.postparse.services.parsers.telegram.telegram_parser import TelegramParser

# Run once interactively to create session
parser = TelegramParser(api_id="...", api_hash="...", phone="+1234567890")
# Follow prompts to enter verification code and 2FA password
```

After session is created, API calls will use the cached session.

## Requirements

- Python 3.10+
- SQLite (included with Python)
- UV package manager (recommended for development)
- FastAPI and Uvicorn (for API server)
- Telegram API credentials (for Telegram extraction)
- Instagram account (for Instagram extraction)
- Ollama server (optional, for content classification)
- JWT secret key (for authentication, set via `JWT_SECRET_KEY` environment variable)

## Project Structure

```
backend/postparse/
├── api/                    # FastAPI REST API
│   ├── routers/            # API route handlers
│   ├── schemas/            # Pydantic request/response models
│   ├── dependencies.py     # Dependency injection
│   ├── middleware.py       # Authentication, CORS, logging
│   └── main.py             # FastAPI application entry point
├── core/                   # Shared components
│   ├── data/               # Database operations
│   ├── utils/              # Configuration utilities
│   └── models/             # Data models
├── services/               # Business logic layers
│   ├── parsers/            # Platform-specific extraction
│   │   ├── telegram/       # Telegram parser
│   │   └── instagram/      # Instagram parser
│   └── analysis/           # Content analysis
│       └── classifiers/    # ML/LLM classifiers
└── visualization/          # Visualization tools
```

## Development

### Running Tests

```bash
# Install with dev dependencies
uv sync --extra dev

# Run tests
uv run pytest tests/

# Run with coverage
uv run pytest --cov=postparse tests/
```

### Contributing

1. Fork the repository
2. Create a feature branch
3. Make your changes
4. Run tests with `uv run pytest tests/`
5. Submit a pull request

See **[11-contributing](docs/11-contributing.md)** for development setup.

## License

MIT License
