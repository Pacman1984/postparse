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
from postparse.services.analysis.classifiers.recipe_classifier import RecipeClassifier

# Extract Telegram messages
count = save_telegram_messages(
    api_id="your_api_id",
    api_hash="your_api_hash",
    phone="+1234567890",
    limit=100
)

# Classify content
db = SocialMediaDatabase()
classifier = RecipeClassifier()

messages = db.get_telegram_messages(limit=10)
for msg in messages:
    if msg['content']:
        result = classifier.predict(msg['content'])
        print(f"Message {msg['message_id']}: {result}")
```

For more examples, see the **[Cookbook](docs/cookbook.md)**.

## Requirements

- Python 3.10+
- SQLite (included with Python)
- UV package manager (recommended for development)
- Telegram API credentials (for Telegram extraction)
- Instagram account (for Instagram extraction)
- Ollama server (optional, for content classification)

## Project Structure

```
backend/postparse/
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
