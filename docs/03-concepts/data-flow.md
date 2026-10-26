# Data Flow

## Pipeline Overview

```
Telegram / Instagram
        ↓  extract
  telegram_messages / instagram_posts
        ↓  enrich run (fetches the links stored with each item)
  link_fetches: title, text and metadata per link (newest ok fetch is searchable)
        ↓  classify db (LLM, uses content + content_expanded)
  content_analysis: labels per item (multi-label, run_id grouped)
```

## Full Update Pipeline

```bash
# 1. Extract new content (incremental)
uv run postparse extract all

# 2. Fetch linked pages, documents, YouTube videos and X posts
uv run postparse enrich run

# 3. Classify with multi-label
uv run postparse classify db --classifier multilabel
```

## Extraction Flow

- **Telegram**: Saved Messages → `telegram_messages` (media to `telegram_downloads_dir`)
- **Instagram**: Saved posts → `instagram_posts` (media to `instagram_downloads_dir`)
- Both: Hashtags extracted from text and stored in separate tables

## Classification Flow

- `classify db` reads `content` and `content_expanded` (when present)
- For each item: calls LLM classifier → saves to `content_analysis`
- Multi-label: multiple rows per item, grouped by `run_id`
