# PostParse

A Python package for extracting and analyzing saved posts from social media platforms.

## Features

- Extract saved messages from Telegram
- Extract saved posts from Instagram
- Download and organize media files
- Analyze content using ML and LLM models
- Structured data storage with SQLite
- Content classification (recipes, tutorials, etc.)

## Documentation

📚 **[Read the full documentation](docs/index.md)** for detailed guides and API reference.

- **[Getting Started](docs/getting_started.md)** - Installation and first steps
- **[Cookbook](docs/cookbook.md)** - Practical examples for common tasks
- **[API Reference](docs/api_reference.md)** - Complete API documentation

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

## Quick Example

```python
from postparse.services.parsers.telegram.telegram_parser import save_telegram_messages
from postparse.core.data.database import SocialMediaDatabase
from postparse.services.analysis.classifiers import RecipeLLMClassifier

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

For more examples, see the **[Cookbook](docs/cookbook.md)**.

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
- **Search**: `/api/v1/search/posts`, `/api/v1/search/messages`
- **Health**: `/health`, `/health/ready`, `/metrics`

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

For more API examples, see the **[API Reference](docs/api_reference.md)**.

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

See **[Getting Started](docs/getting_started.md)** for development setup.

## License

MIT License
