# PostParse Overview

PostParse extracts, stores, and analyzes saved posts from social media platforms. It provides a unified interface for content from Telegram and Instagram, with built-in classification using ML and LLM models.

## Who It's For

**Use PostParse when you want to:**
- Extract and organize saved messages from Telegram
- Download and catalog saved Instagram posts
- Analyze content (identify recipes, tutorials, etc.)
- Build a searchable database of saved content
- Process social media data for ML or data science

**Consider alternatives if:**
- You only need basic API access (use platform SDKs directly)
- You need real-time streaming (PostParse focuses on saved/archived content)
- You require other platforms (currently Telegram and Instagram only)

## Key Features

- **Multi-platform**: Telegram and Instagram
- **Structured storage**: SQLite with well-designed schema
- **Content analysis**: Built-in classifiers (recipe detection, multi-class, multi-label)
- **Media handling**: Automatic download and organization
- **Configuration**: TOML-based config system
- **Rate limiting**: Respects platform guidelines

## Project Status

Core parsing and storage are stable. The analysis module is actively expanding with additional classifiers.

## Documentation Map

| Document | Purpose |
|----------|---------|
| [02-quickstart](02-quickstart.md) | Prerequisites, install, minimal example |
| [03-concepts/architecture](03-concepts/architecture.md) | System architecture |
| [03-concepts/database](03-concepts/database.md) | Database schema |
| [04-installation](04-installation.md) | Dependencies, env vars |
| [05-usage/cli-reference](05-usage/cli-reference.md) | Full CLI reference |
| [07-configuration](07-configuration.md) | Config, LLM providers |
| [08-examples/recipes](08-examples/recipes.md) | Copy-pastable examples |
| [06-api/endpoints](06-api/endpoints.md) | REST API |
| [06-api/python-reference](06-api/python-reference.md) | Python API |
