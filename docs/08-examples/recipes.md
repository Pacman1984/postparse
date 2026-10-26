# Recipes

Copy-pastable examples for common tasks.

## Full Pipeline

```bash
uv run postparse extract all
uv run postparse enrich run
uv run postparse classify db --classifier multilabel
```

## 1. Extract Telegram Messages

```python
from postparse.services.parsers.telegram.telegram_parser import save_telegram_messages

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
from postparse.services.parsers.instagram.instagram_parser import InstaloaderParser
from postparse.core.data.database import SocialMediaDatabase

db = SocialMediaDatabase("my_data.db")
parser = InstaloaderParser(username="user", password="pass")
saved_count = parser.save_posts_to_db(db, limit=50, force_update=False)
print(f"Saved {saved_count} posts")
```

## 3. Classify and Save Results

```python
from postparse.core.data.database import SocialMediaDatabase
from postparse.services.analysis.classifiers import RecipeLLMClassifier

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

## 6. Enrich Links

```bash
# Fetch linked pages, PDFs, YouTube videos (oEmbed, yt-dlp, transcript) and X posts
uv run postparse enrich run --source telegram --limit 100
uv run postparse enrich run --domain youtube.com --domain youtu.be
uv run postparse enrich status
```

Each fetch is stored per link (`link_fetches`); the newest successful fetch is
part of the item's search document. Instagram links are never fetched. Failed
links are retried with exponential backoff on later runs. YouTube metadata
beyond oEmbed needs the `youtube` extra (`uv sync --extra youtube`).

## 7. Programmatic Enrichment

```python
import asyncio

from postparse.core.db.models import Link
from postparse.enrichment import EnrichmentOptions
from postparse.enrichment.fetchers import FetchRouter


async def main() -> None:
    async with FetchRouter.default_router(EnrichmentOptions()) as router:
        result = await router.fetch(Link(0, "https://arxiv.org/abs/2401.00001", "arxiv.org"))
        print(result.status, result.title, (result.text or "")[:200])


asyncio.run(main())
```
