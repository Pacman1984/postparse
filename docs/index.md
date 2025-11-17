# PostParse Documentation

## Overview

PostParse is a Python package for extracting, storing, and analyzing saved posts from social media platforms. It provides a unified interface for working with content from Telegram and Instagram, with built-in support for content classification using machine learning and LLM models.

## Why PostParse?

**Use PostParse when you want to:**
- Extract and organize your saved messages from Telegram
- Download and catalog your saved Instagram posts
- Analyze social media content (e.g., identify recipes, tutorials, etc.)
- Build a searchable database of your saved content
- Process social media data for ML/data science projects

**Choose an alternative if:**
- You only need basic API access (use platform SDKs directly)
- You need real-time streaming (PostParse focuses on saved/archived content)
- You require support for other platforms (currently supports Telegram & Instagram only)

## Quick Example

Here's a minimal example showing how to extract Telegram messages and classify content:

```python
from postparse.telegram.telegram_parser import TelegramParser
from postparse.data.database import SocialMediaDatabase
from postparse.analysis.classifiers.recipe_classifier import RecipeClassifier

# Initialize database
db = SocialMediaDatabase("my_data.db")

# Extract Telegram messages
async with TelegramParser(
    api_id="your_api_id",
    api_hash="your_api_hash",
    phone="+1234567890"
) as parser:
    await parser.save_messages_to_db(db, limit=100)

# Classify content
classifier = RecipeClassifier()
messages = db.get_telegram_messages(limit=10)

for msg in messages:
    if msg['content']:
        result = classifier.predict(msg['content'])
        print(f"Message {msg['message_id']}: {result}")
```

## Documentation Structure

- **[Getting Started](getting_started.md)** - Installation, setup, and your first steps
- **[Cookbook](cookbook.md)** - Practical recipes for common tasks
- **[API Reference](api_reference.md)** - Complete reference for all public APIs

## Key Features

- **Multi-Platform Support**: Extract data from Telegram and Instagram
- **Structured Storage**: SQLite database with well-designed schema
- **Content Analysis**: Built-in classifiers for recipe detection and more
- **Media Handling**: Automatic download and organization of media files
- **Configuration**: Flexible TOML-based configuration system
- **Rate Limiting**: Smart rate limiting to respect platform guidelines

## Project Status

PostParse is under active development. The core parsing and storage functionality is stable, while the analysis module is being expanded with additional classifiers.

## Getting Help

- Check the [Getting Started](getting_started.md) guide for setup instructions
- Browse the [Cookbook](cookbook.md) for task-oriented examples
- Consult the [API Reference](api_reference.md) for detailed function documentation
- Report issues on the project's GitHub repository

