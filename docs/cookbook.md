# Cookbook

This cookbook provides practical recipes for common tasks with PostParse. Each recipe includes a complete, working example with explanations.

## Table of Contents

1. [Extract and Store Telegram Messages](#recipe-1-extract-and-store-telegram-messages)
2. [Batch Process Instagram Posts](#recipe-2-batch-process-instagram-posts)
3. [Classify Content with Recipe Detection](#recipe-3-classify-content-with-recipe-detection)
4. [Search and Filter Saved Content](#recipe-4-search-and-filter-saved-content)
5. [Build a Content Analysis Pipeline](#recipe-5-build-a-content-analysis-pipeline)

---

## Recipe 1: Extract and Store Telegram Messages

**Goal:** Extract your saved Telegram messages and store them in a local database.

**Key APIs:** [`TelegramParser`](api_reference.md#postparsetelegramtelegram_parsertelegramparser), [`save_telegram_messages`](api_reference.md#postparsetelegramtelegram_parsersave_telegram_messages), [`SocialMediaDatabase`](api_reference.md#postparsedatadatabasesocialmediadatabase)

```python
from postparse.telegram.telegram_parser import save_telegram_messages

# Simple approach: Use the helper function
count = save_telegram_messages(
    api_id="your_api_id",
    api_hash="your_api_hash",
    phone="+1234567890",
    db_path="my_telegram_data.db",
    limit=100,  # Extract 100 most recent messages
    force_update=False  # Skip messages already in database
)

print(f"Successfully saved {count} messages")
```

**Advanced: Async approach with more control**

```python
import asyncio
from postparse.telegram.telegram_parser import TelegramParser
from postparse.data.database import SocialMediaDatabase

async def extract_with_progress():
    db = SocialMediaDatabase("my_telegram_data.db")
    
    async with TelegramParser(
        api_id="your_api_id",
        api_hash="your_api_hash",
        phone="+1234567890",
        cache_dir="data/cache",  # Custom cache location
        downloads_dir="data/telegram_media"  # Custom media location
    ) as parser:
        # Save to database with progress tracking
        count = await parser.save_messages_to_db(
            db=db,
            limit=None,  # Extract all messages
            max_requests_per_session=200,  # Limit API calls per session
            force_update=False
        )
        print(f"Saved {count} messages")

asyncio.run(extract_with_progress())
```

**What's happening:**
- The parser authenticates with Telegram (prompts for code on first run)
- Downloads media files to organized directories by date
- Stores messages with metadata (views, forwards, hashtags) in SQLite
- Skips existing messages to avoid duplicates (unless `force_update=True`)
- Implements smart rate limiting to respect Telegram's API limits

---

## Recipe 2: Batch Process Instagram Posts

**Goal:** Extract saved Instagram posts efficiently with batch processing and error handling.

**Key APIs:** [`InstaloaderParser`](api_reference.md#postparseinstagraminstagram_parserinstaloaderparser), [`SocialMediaDatabase`](api_reference.md#postparsedatadatabasesocialmediadatabase)

```python
from postparse.instagram.instagram_parser import InstaloaderParser
from postparse.data.database import SocialMediaDatabase
import logging

# Set up logging to track progress
logging.basicConfig(level=logging.INFO)

# Initialize database and parser
db = SocialMediaDatabase("instagram_data.db")
parser = InstaloaderParser(
    username="your_username",
    password="your_password",
    session_file="instagram_session",  # Reuse login session
    min_delay=5.0,  # Minimum delay between requests
    max_delay=15.0  # Maximum delay (adaptive)
)

# Extract and save with batch optimization
try:
    saved_count = parser.save_posts_to_db(
        db=db,
        limit=50,  # Extract 50 posts
        force_update=False,  # Skip existing posts
        batch_size=100  # Process 100 posts per batch
    )
    print(f"Successfully saved {saved_count} posts")
except Exception as e:
    print(f"Error during extraction: {e}")
    print("Partial data may have been saved. Check the database.")
```

**Incremental updates:**

```python
# First run: Extract initial batch
parser.save_posts_to_db(db, limit=100)

# Later: Extract only new posts (skips existing)
new_count = parser.save_posts_to_db(db, limit=50, force_update=False)
print(f"Added {new_count} new posts")
```

**What's happening:**
- Parser logs in to Instagram (reuses session file to avoid repeated logins)
- Implements adaptive rate limiting to avoid Instagram blocks
- Batch checks for existing posts (much faster than individual checks)
- Extracts hashtags and mentions from captions
- Handles errors gracefully and continues processing

---

## Recipe 3: Classify Content with Recipe Detection

**Goal:** Analyze saved content to identify recipes using LLM classification with structured output.

**Key APIs:** [`RecipeLLMClassifier`](api_reference.md#postparseservicesanalysisclassifiersllmrecipellmclassifier), [`SocialMediaDatabase`](api_reference.md#postparsedatadatabasesocialmediadatabase)

```python
from postparse.core.data.database import SocialMediaDatabase
from postparse.services.analysis.classifiers import RecipeLLMClassifier

# Initialize database and classifier (uses LangChain + LiteLLM)
db = SocialMediaDatabase("my_data.db")
classifier = RecipeLLMClassifier()  # Supports Ollama, LM Studio, OpenAI, etc.

# Classify Telegram messages with detailed metadata
messages = db.get_telegram_messages(limit=100)
recipe_count = 0

for msg in messages:
    if msg['content']:
        result = classifier.predict(msg['content'])
        
        if result.label == "recipe":
            recipe_count += 1
            print(f"\nRecipe found in message {msg['message_id']}")
            print(f"Confidence: {result.confidence:.2f}")
            print(f"Cuisine: {result.details.get('cuisine_type', 'Unknown')}")
            print(f"Difficulty: {result.details.get('difficulty', 'Unknown')}")
            print(f"Meal type: {result.details.get('meal_type', 'Unknown')}")
            print(f"Content preview: {msg['content'][:100]}...")

print(f"\nFound {recipe_count} recipes out of {len(messages)} messages")
```

**Batch Classification for Performance**

```python
# Classify Instagram posts in batch
posts = db.get_instagram_posts(limit=50)
captions = [post['caption'] for post in posts if post['caption']]

# Batch prediction is more efficient
results = classifier.predict_batch(captions)

for post, result in zip(posts, results):
    if result.label == "recipe":
        print(f"\nRecipe in post {post['shortcode']}")
        print(f"  Confidence: {result.confidence:.2f}")
        print(f"  Details: {result.details}")
```

**What's happening:**
- `RecipeLLMClassifier` uses LangChain + LiteLLM for universal LLM support
- Zero-shot classification (no training required)
- Returns structured Pydantic models with rich metadata
- Automatically works with ANY LiteLLM provider (Ollama, LM Studio, OpenAI, etc.)
- Includes confidence scores and detailed recipe attributes

---

## Recipe 4: Search and Filter Saved Content

**Goal:** Query and filter your saved content using various criteria.

**Key APIs:** [`SocialMediaDatabase`](api_reference.md#postparsedatadatabasesocialmediadatabase) query methods

```python
from postparse.data.database import SocialMediaDatabase
from datetime import datetime, timedelta

db = SocialMediaDatabase("my_data.db")

# Search by hashtag
recipe_posts = db.get_posts_by_hashtag("recipe")
print(f"Found {len(recipe_posts)} posts with #recipe")

for post in recipe_posts[:5]:  # Show first 5
    print(f"- {post['owner_username']}: {post['caption'][:50]}...")

# Search by date range
end_date = datetime.now()
start_date = end_date - timedelta(days=30)  # Last 30 days

recent_posts = db.get_posts_by_date_range(start_date, end_date)
print(f"\nFound {len(recent_posts)} posts from last 30 days")

# Get specific post details
post = db.get_instagram_post("ABC123xyz")  # Use actual shortcode
if post:
    print(f"\nPost details:")
    print(f"Owner: {post['owner_username']}")
    print(f"Likes: {post['likes']}")
    print(f"Hashtags: {', '.join(post['hashtags'])}")
    print(f"Mentions: {', '.join(post['mentions'])}")

# Check if content exists before fetching
if db.post_exists("ABC123xyz"):
    print("Post already in database")
else:
    print("Post not found, need to fetch")
```

**Complex filtering with SQL:**

```python
import sqlite3

# For complex queries, use SQL directly
conn = sqlite3.connect("my_data.db")
cursor = conn.cursor()

# Find posts with multiple hashtags
cursor.execute("""
    SELECT p.shortcode, p.caption, COUNT(h.hashtag) as hashtag_count
    FROM instagram_posts p
    JOIN instagram_hashtags h ON p.id = h.post_id
    WHERE h.hashtag IN ('recipe', 'cooking', 'food')
    GROUP BY p.id
    HAVING hashtag_count >= 2
    ORDER BY p.likes DESC
    LIMIT 10
""")

results = cursor.fetchall()
print(f"Found {len(results)} posts with multiple relevant hashtags")
for shortcode, caption, count in results:
    print(f"- {shortcode}: {count} hashtags")

conn.close()
```

**What's happening:**
- Database methods provide convenient high-level queries
- Hashtags and mentions are stored in separate tables for efficient searching
- Date-based queries use ISO format timestamps
- For complex queries, you can use SQL directly on the SQLite database

---

## Recipe 5: Build a Content Analysis Pipeline

**Goal:** Create an end-to-end pipeline that extracts, stores, and analyzes content.

**Key APIs:** All major modules combined

```python
import asyncio
from postparse.services.parsers.telegram.telegram_parser import TelegramParser
from postparse.services.parsers.instagram.instagram_parser import InstaloaderParser
from postparse.core.data.database import SocialMediaDatabase
from postparse.services.analysis.classifiers import RecipeLLMClassifier

class ContentPipeline:
    """End-to-end content extraction and analysis pipeline."""
    
    def __init__(self, db_path="content_pipeline.db"):
        self.db = SocialMediaDatabase(db_path)
        self.classifier = RecipeLLMClassifier()  # LangChain + LiteLLM
        self.stats = {
            'telegram_messages': 0,
            'instagram_posts': 0,
            'recipes_found': 0
        }
    
    async def extract_telegram(self, api_id, api_hash, phone, limit=100):
        """Extract Telegram messages."""
        print("Extracting Telegram messages...")
        async with TelegramParser(api_id=api_id, api_hash=api_hash, phone=phone) as parser:
            count = await parser.save_messages_to_db(self.db, limit=limit)
            self.stats['telegram_messages'] = count
            print(f"Extracted {count} Telegram messages")
    
    def extract_instagram(self, username, password, limit=50):
        """Extract Instagram posts."""
        print("Extracting Instagram posts...")
        parser = InstaloaderParser(username=username, password=password)
        count = parser.save_posts_to_db(self.db, limit=limit)
        self.stats['instagram_posts'] = count
        print(f"Extracted {count} Instagram posts")
    
    def analyze_content(self):
        """Analyze all content for recipes."""
        print("Analyzing content...")
        
        # Analyze Telegram messages
        messages = self.db.get_telegram_messages()
        for msg in messages:
            if msg['content']:
                result = self.classifier.predict(msg['content'])
                if result.label == "recipe":
                    self.stats['recipes_found'] += 1
                    print(f"  Recipe found: {result.details.get('cuisine_type', 'Unknown cuisine')}")
        
        # Analyze Instagram posts
        posts = self.db.get_instagram_posts()
        for post in posts:
            if post['caption']:
                result = self.classifier.predict(post['caption'])
                if result.label == "recipe":
                    self.stats['recipes_found'] += 1
                    print(f"  Recipe found: {result.details.get('meal_type', 'Unknown type')}")
        
        print(f"Analysis complete. Found {self.stats['recipes_found']} recipes")
    
    def print_summary(self):
        """Print pipeline statistics."""
        print("\n=== Pipeline Summary ===")
        print(f"Telegram messages: {self.stats['telegram_messages']}")
        print(f"Instagram posts: {self.stats['instagram_posts']}")
        print(f"Recipes found: {self.stats['recipes_found']}")
        total = self.stats['telegram_messages'] + self.stats['instagram_posts']
        if total > 0:
            percentage = (self.stats['recipes_found'] / total) * 100
            print(f"Recipe percentage: {percentage:.1f}%")

# Run the pipeline
async def main():
    pipeline = ContentPipeline()
    
    # Extract from both platforms
    await pipeline.extract_telegram(
        api_id="your_api_id",
        api_hash="your_api_hash",
        phone="+1234567890",
        limit=100
    )
    
    pipeline.extract_instagram(
        username="your_username",
        password="your_password",
        limit=50
    )
    
    # Analyze all content
    pipeline.analyze_content()
    
    # Show results
    pipeline.print_summary()

# Run the pipeline
asyncio.run(main())
```

**What's happening:**
- Pipeline class encapsulates the entire workflow
- Extracts data from multiple sources sequentially
- Stores everything in a single database
- Analyzes all content with consistent classification
- Tracks statistics throughout the process
- Can be extended with additional sources or classifiers

**Next steps:**
- Add more classifiers (tutorials, news articles, etc.)
- Export results to CSV or JSON for further analysis
- Schedule pipeline to run periodically with cron
- Add notification system for interesting content
- Integrate with data visualization tools

---

## Tips and Best Practices

### Rate Limiting
- Always respect platform rate limits to avoid account restrictions
- Use the configuration file to adjust delays between requests
- For Instagram, start with longer delays (10-30s) and reduce if stable

### Error Handling
- Wrap extraction calls in try-except blocks
- Check for partial data in database after errors
- Use `force_update=False` to resume interrupted extractions

### Performance
- Use batch operations when processing many items
- Check for existing content before fetching to avoid duplicates
- For large datasets, process in smaller chunks with limits

### Configuration
- Store credentials in `config/.env` (never commit to version control)
- Customize delays and timeouts in `config/config.toml`
- Use different database files for different projects

### Data Management
- Regularly backup your SQLite database files
- Use descriptive database names for different projects
- Monitor database size and clean old data if needed

