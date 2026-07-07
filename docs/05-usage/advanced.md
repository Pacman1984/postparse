# Advanced Usage

## Batch Extraction

```python
from backend.postparse.services.parsers.instagram.instagram_parser import InstaloaderParser
from backend.postparse.core.data.database import SocialMediaDatabase

db = SocialMediaDatabase("data.db")
parser = InstaloaderParser(username="user", password="pass", min_delay=5.0, max_delay=15.0)

saved_count = parser.save_posts_to_db(db, limit=50, force_update=False, batch_size=100)
```

## Multi-Class Classification

```bash
postparse classify db --classifier multiclass \
  --classes '{"recipe": "Cooking", "tech": "Technology", "other": "Other"}'
```

## Custom Provider

```python
from backend.postparse.services.analysis.classifiers import RecipeLLMClassifier

classifier = RecipeLLMClassifier(provider_name='openai')
result = classifier.predict("Boil pasta, add sauce")
```

## API Server

```bash
# Development
uv run uvicorn backend.postparse.api.main:app --reload --port 8000

# Production
uv run uvicorn backend.postparse.api.main:app --workers 4 --port 8000
```

Interactive docs: http://localhost:8000/docs
