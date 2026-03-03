# Python API Reference

## SocialMediaDatabase

```python
from backend.postparse.core.data.database import SocialMediaDatabase

db = SocialMediaDatabase("data/social_media.db")
```

### Content Queries

| Method | Returns |
|--------|---------|
| `get_instagram_posts(limit=None)` | List of post dicts |
| `get_telegram_messages(limit=None)` | List of message dicts |
| `search_instagram_posts(hashtags, limit, cursor)` | (posts, next_cursor) |
| `search_telegram_messages(hashtags, limit, cursor)` | (messages, next_cursor) |
| `get_instagram_post(shortcode)` | Single post or None |
| `post_exists(shortcode)` | bool |
| `message_exists(message_id)` | bool |

### Classification

| Method | Purpose |
|--------|---------|
| `save_classification_result(content_id, content_source, classifier_name, label, confidence, details=..., reasoning=..., llm_metadata=..., run_id=...)` | Save result |
| `get_classification_results(content_id, content_source, classifier_name=..., run_id=...)` | Get results |
| `has_classification(content_id, content_source, classifier_name, llm_model=...)` | Check if classified |
| `get_classification_id(...)` | Get analysis ID for update |
| `update_classification(analysis_id, label, confidence, ...)` | Update existing |

## Telegram Parser

```python
from backend.postparse.services.parsers.telegram.telegram_parser import (
    save_telegram_messages,
    TelegramParser,
)

# Sync helper
count = save_telegram_messages(
    api_id="...", api_hash="...", phone="+1234567890",
    db_path="data.db", limit=100, force_update=False
)

# Async (more control)
async with TelegramParser(api_id="...", api_hash="...", phone="...") as parser:
    count = await parser.save_messages_to_db(db, limit=100)
```

## Instagram Parser

```python
from backend.postparse.services.parsers.instagram.instagram_parser import InstaloaderParser

parser = InstaloaderParser(username="...", password="...")
count = parser.save_posts_to_db(db, limit=50, force_update=False)
```

## Classifiers

```python
from backend.postparse.services.analysis.classifiers import (
    RecipeLLMClassifier,
    MultiClassLLMClassifier,
    MultiLabelLLMClassifier,
)

# Recipe (binary)
clf = RecipeLLMClassifier(provider_name='openai')
result = clf.predict("Boil pasta, add sauce")
# result.label, result.confidence, result.details

# Multi-class (custom categories)
clf = MultiClassLLMClassifier(classes={"recipe": "...", "tech": "..."})
result = clf.predict("...")

# Multi-label
clf = MultiLabelLLMClassifier(provider_name='openai')
result = clf.predict_multilabel("...")
# result.labels (list of LabelScore), result.reasoning
```

## Enrichment

```python
from backend.postparse.services.enrichment import YouTubeEnricher, LinkScraper, XEnricher

yt = YouTubeEnricher(timeout=10)
result = yt.enrich("", source_url="https://youtube.com/watch?v=abc")

scraper = LinkScraper(timeout=15)
result = scraper.enrich("", source_url="https://example.com/article")

x = XEnricher(timeout=10)
result = x.enrich("", source_url="https://x.com/user/status/123")
```
