# Recipes

Copy-pastable examples for common tasks.

## Full Pipeline

```bash
uv run postparse extract all
uv run postparse enrich scrape
uv run postparse classify db --classifier multilabel
```

## 1. Extract Telegram Messages

```python
from backend.postparse.services.parsers.telegram.telegram_parser import save_telegram_messages

count = save_telegram_messages(
    api_id="your_api_id",
    api_hash="your_api_hash",
    phone="+1234567890",
    db_path="my_data.db",
    limit=100,
    force_update=False
)
print(f"Saved {count} messages")
```

## 2. Extract Instagram Posts

```python
from backend.postparse.services.parsers.instagram.instagram_parser import InstaloaderParser
from backend.postparse.core.data.database import SocialMediaDatabase

db = SocialMediaDatabase("my_data.db")
parser = InstaloaderParser(username="user", password="pass")
saved_count = parser.save_posts_to_db(db, limit=50, force_update=False)
print(f"Saved {saved_count} posts")
```

## 3. Classify and Save Results

```python
from backend.postparse.core.data.database import SocialMediaDatabase
from backend.postparse.services.analysis.classifiers import RecipeLLMClassifier

db = SocialMediaDatabase("my_data.db")
classifier = RecipeLLMClassifier()

for msg in db.get_telegram_messages(limit=100):
    if not msg['content'] or db.has_classification(msg['id'], 'telegram', 'recipe_llm'):
        continue
    result = classifier.predict(msg['content'])
    db.save_classification_result(
        content_id=msg['id'],
        content_source='telegram',
        classifier_name='recipe_llm',
        label=result.label,
        confidence=result.confidence,
        details=result.details,
        llm_metadata=classifier.get_llm_metadata()
    )
```

## 4. Search by Hashtag

```bash
postparse search posts --hashtag recipe
postparse search messages --hashtag cooking
```

## 5. Multi-Label Classification

```bash
uv run postparse classify db --classifier multilabel --source telegram --limit 100
```

## 6. Enrich with URL Scraping

```bash
# Scrape URLs (YouTube, X, generic links) → content_expanded
uv run postparse enrich scrape --source telegram --limit 100

# Classify (uses content + content_expanded)
uv run postparse classify db --classifier multilabel
```

Scraped text (title, description, body) is stored in `content_expanded`. Classify uses `content` + `content_expanded` when both exist.

## 7. Programmatic Enrichment

```python
from backend.postparse.services.enrichment import YouTubeEnricher, LinkScraper

# YouTube
yt = YouTubeEnricher(timeout=10.0)
result = yt.enrich("", source_url="https://youtube.com/watch?v=abc")
print(result.metadata["title"], result.metadata["author"])

# Generic link
scraper = LinkScraper(timeout=15.0)
result = scraper.enrich("", source_url="https://arxiv.org/abs/2401.00001")
print(result.generated_text)
```
