# Architecture

## System Overview

PostParse is a Python package with a layered structure:

```
backend/postparse/
├── api/                    # FastAPI REST API
│   ├── routers/            # Route handlers
│   ├── schemas/            # Pydantic models
│   ├── dependencies.py     # Dependency injection
│   ├── middleware.py       # Auth, CORS, logging
│   └── main.py             # Application entry
├── core/                   # Shared components
│   ├── data/               # Database operations
│   ├── utils/              # Configuration
│   └── models/             # Data models
├── services/               # Business logic
│   ├── parsers/            # Platform extraction
│   │   ├── telegram/       # Telegram parser
│   │   └── instagram/      # Instagram parser
│   └── analysis/           # Content analysis
│       └── classifiers/    # ML/LLM classifiers
└── cli/                    # Command-line interface
```

## Database Schema

- **Content tables**: `telegram_messages`, `instagram_posts`, `instagram_hashtags`, `telegram_hashtags`
- **Analysis**: `content_analysis` (links to content via `content_id` + `content_source`)
- **Enrichment**: `content_expanded` column on content tables; `content_enrichments` for scraped URL data

## Key Components

| Component | Purpose |
|-----------|---------|
| `SocialMediaDatabase` | SQLite operations, query methods |
| `TelegramParser` | Extract from Saved Messages |
| `InstaloaderParser` | Extract from Instagram saved posts |
| `RecipeLLMClassifier` | Binary recipe/not-recipe |
| `MultiClassLLMClassifier` | Custom categories |
| `MultiLabelLLMClassifier` | Multiple labels per item |
