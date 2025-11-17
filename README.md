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

```bash
pip install postparse
```

Or using uv:

```bash
uv pip install postparse
```

## Quick Example

```python
from postparse.telegram.telegram_parser import save_telegram_messages
from postparse.data.database import SocialMediaDatabase
from postparse.analysis.classifiers.recipe_classifier import RecipeClassifier

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

- Python 3.6+
- SQLite (included with Python)
- Telegram API credentials (for Telegram extraction)
- Instagram account (for Instagram extraction)
- Ollama server (optional, for content classification)

## Project Structure

```
src/postparse/
├── data/                  # Database operations
├── telegram/             # Telegram parser
├── instagram/            # Instagram parser
├── analysis/             # Content classifiers
│   └── classifiers/      # ML/LLM classifiers
└── utils/                # Configuration utilities
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

See **[Getting Started](docs/getting_started.md)** for development setup.

## License

MIT License
