# API Reference

This is the authoritative reference for PostParse's public API. All classes and functions documented here are part of the stable, supported interface.

## REST API Reference

PostParse provides a REST API built with FastAPI for programmatic access to all features.

### Base URL

```
http://localhost:8000/api/v1
```

### Authentication

Authentication is optional and can be enabled via configuration. When enabled, include JWT token in requests:

```bash
curl -H "Authorization: Bearer YOUR_JWT_TOKEN" http://localhost:8000/api/v1/classify/recipe
```

### API Endpoints

#### Telegram Endpoints

**POST /api/v1/telegram/extract**

Trigger Telegram message extraction.

- **Request body:** `TelegramExtractRequest` (api_id, api_hash, phone, limit, force_update)
- **Response:** `TelegramExtractResponse` (job_id, status, message_count)
- **Status codes:** 200 (success), 400 (invalid request), 401 (unauthorized), 503 (service unavailable)

**Example:**

```bash
curl -X POST http://localhost:8000/api/v1/telegram/extract \
  -H "Content-Type: application/json" \
  -d '{
    "api_id": "12345678",
    "api_hash": "0123456789abcdef0123456789abcdef",
    "phone": "+1234567890",
    "limit": 100
  }'
```

**GET /api/v1/telegram/messages**

List extracted Telegram messages with pagination.

- **Query params:** 
  - `limit` (int): Maximum results to return (default: 50, max: 100)
  - `offset` (int): Number of results to skip (accepted but not yet implemented)
  - `channel_username` (str, optional): Filter by channel (accepted but not yet implemented)
- **Response:** `PaginatedResponse[TelegramMessageSchema]`

**Note:** Currently supports basic limit-based pagination. Advanced filtering (offset, channel_username, date range, content type) is planned for a future phase.

**Example:**

```bash
curl http://localhost:8000/api/v1/telegram/messages?limit=20
```

#### Instagram Endpoints

**POST /api/v1/instagram/extract**

Trigger Instagram post extraction.

- **Request body:** `InstagramExtractRequest` (username, password, limit, force_update, use_api)
- **Response:** `InstagramExtractResponse` (job_id, status, post_count)

**Example:**

```bash
curl -X POST http://localhost:8000/api/v1/instagram/extract \
  -H "Content-Type: application/json" \
  -d '{
    "username": "cooking_profile",
    "password": "secret123",
    "limit": 50,
    "use_api": false
  }'
```

**GET /api/v1/instagram/posts**

List extracted Instagram posts with pagination.

- **Query params:** 
  - `limit` (int): Maximum results to return (default: 50, max: 100)
  - `offset` (int): Number of results to skip (accepted but not yet implemented)
  - `owner_username` (str, optional): Filter by owner (accepted but not yet implemented)
- **Response:** `PaginatedResponse[InstagramPostSchema]`

**Note:** Currently supports basic limit-based pagination. Advanced filtering (offset, owner_username, hashtags, date range) is planned for a future phase.

**Example:**

```bash
curl http://localhost:8000/api/v1/instagram/posts?limit=20
```

#### Classification Endpoints

**POST /api/v1/classify/recipe**

Classify single text as recipe or non-recipe.

- **Request body:** `ClassifyRequest` (text, classifier_type, provider_name)
- **Response:** `ClassifyResponse` (label, confidence, details, processing_time)

**Note:** Currently only the `"llm"` classifier type is supported. A basic rule-based classifier is planned for a future phase.

**Example:**

```bash
curl -X POST http://localhost:8000/api/v1/classify/recipe \
  -H "Content-Type: application/json" \
  -d '{
    "text": "Boil pasta for 10 minutes, drain, add tomato sauce and basil",
    "classifier_type": "llm",
    "provider_name": "lm_studio"
  }'
```

**Response:**

```json
{
  "label": "recipe",
  "confidence": 0.95,
  "details": {
    "cuisine_type": "italian",
    "difficulty": "easy",
    "meal_type": "dinner",
    "ingredients_count": 5
  },
  "processing_time": 0.234,
  "classifier_used": "llm"
}
```

**POST /api/v1/classify/batch**

Classify multiple texts in batch.

- **Request body:** `BatchClassifyRequest` (texts, classifier_type, provider_name)
- **Response:** `BatchClassifyResponse` (results, total_processed, failed_count)

**Example:**

```bash
curl -X POST http://localhost:8000/api/v1/classify/batch \
  -H "Content-Type: application/json" \
  -d '{
    "texts": [
      "Boil pasta for 10 minutes",
      "Just finished watching a great movie",
      "Mix flour, eggs, and milk to make pancakes"
    ],
    "classifier_type": "llm"
  }'
```

#### Search Endpoints

**GET /api/v1/search/posts**

Search Instagram posts with basic filters.

- **Query params:** 
  - `hashtags` (list): Filter by hashtags (currently only first hashtag is used; OR logic for multiple hashtags is planned)
  - `owner_username` (str): Filter by owner (not yet implemented)
  - `limit` (int): Maximum results (default: 50, max: 100)
  - `offset` (int): Results to skip (not yet implemented)
- **Response:** `SearchResponse[PostSearchResult]`

**Note:** Currently supports single hashtag filtering. Advanced features (multiple hashtags with OR logic, date_range, content_type, owner_username, offset) are planned for future phases.

**Example:**

```bash
curl "http://localhost:8000/api/v1/search/posts?hashtags=recipe&limit=20"
```

**Response:**

```json
{
  "results": [...],
  "total_count": 20,
  "filters_applied": {"hashtags": ["recipe"]},
  "pagination": {"limit": 20, "offset": 0, "next_offset": 20}
}
```

**GET /api/v1/search/messages**

Search Telegram messages with basic filters.

- **Query params:** 
  - `hashtags` (list): Filter by hashtags (not yet implemented)
  - `channel_username` (str): Filter by channel (not yet implemented)
  - `limit` (int): Maximum results (default: 50, max: 100)
  - `offset` (int): Results to skip (not yet implemented)
- **Response:** `SearchResponse[MessageSearchResult]`

**Note:** Currently returns all messages with basic limit-based pagination. Advanced filtering (hashtags, date_range, content_type, channel_username, offset) is planned for future phases.

**Example:**

```bash
curl "http://localhost:8000/api/v1/search/messages?limit=50"
```

#### Health Endpoints

**GET /health**

Basic health check.

- **Response:** `HealthResponse` (status, version, timestamp)

**Example:**

```bash
curl http://localhost:8000/health
```

**Response:**

```json
{
  "status": "ok",
  "version": "0.1.0",
  "timestamp": "2025-11-19T10:30:00Z",
  "details": null
}
```

**GET /health/ready**

Readiness probe (checks database and LLM provider).

- **Response:** 200 (ready) or 503 (not ready)

**GET /metrics**

Basic metrics (request counts, database stats).

- **Response:** JSON with metrics data

### Error Responses

All errors follow a standard format:

```json
{
  "error_code": "INVALID_REQUEST",
  "message": "Text field is required",
  "details": {"field": "text", "issue": "missing"}
}
```

**Common error codes:**

- `INVALID_REQUEST`: Validation error (400)
- `UNAUTHORIZED`: Authentication failed (401)
- `NOT_FOUND`: Resource not found (404)
- `RATE_LIMIT_EXCEEDED`: Too many requests (429)
- `LLM_PROVIDER_ERROR`: LLM service unavailable (503)
- `INTERNAL_ERROR`: Server error (500)

### Interactive Documentation

Explore the API interactively at:

- **Swagger UI:** http://localhost:8000/docs
- **ReDoc:** http://localhost:8000/redoc

### WebSocket Endpoints

PostParse provides WebSocket endpoints for receiving real-time progress updates during extraction jobs.

#### Unified Endpoint (Recommended)

**`ws://localhost:8000/api/v1/jobs/ws/progress/{job_id}`**

Works for all platforms (Telegram, Instagram). This is the recommended endpoint for new integrations.

#### Platform-Specific Endpoints (Backward Compatibility)

- **Telegram:** `ws://localhost:8000/api/v1/telegram/ws/progress/{job_id}`
- **Instagram:** `ws://localhost:8000/api/v1/instagram/ws/progress/{job_id}`

All endpoints provide identical functionality and message format.

#### Connection Flow

1. Start an extraction job via REST API (returns `job_id`)
2. Connect to WebSocket endpoint with the `job_id`
3. Receive real-time progress updates as JSON messages
4. Connection closes automatically when job completes or fails

#### WebSocket Message Format

Progress updates are sent as JSON messages with the following structure:

```json
{
    "job_id": "550e8400-e29b-41d4-a716-446655440000",
    "status": "running",
    "progress": 65,
    "messages_processed": 65,
    "errors": [],
    "timestamp": "2025-11-23T10:30:00Z"
}
```

**Fields:**
- `job_id` (string): Unique job identifier (UUID)
- `status` (string): Current job status - one of: `"pending"`, `"running"`, `"completed"`, `"failed"`
- `progress` (integer): Completion percentage (0-100)
- `messages_processed` (integer): Number of messages/posts processed so far
- `errors` (array): List of error messages encountered (empty if no errors)
- `timestamp` (string): ISO 8601 timestamp of the update

#### Job Status Lifecycle

Jobs progress through the following states:

1. **`pending`**: Job is queued but not started yet
   - `progress`: 0
   - `messages_processed`: 0

2. **`running`**: Job is actively processing
   - `progress`: 1-99 (increments as work progresses)
   - `messages_processed`: Number processed so far
   - Updates sent periodically (typically every few seconds)

3. **`completed`**: Job finished successfully
   - `progress`: 100
   - `messages_processed`: Total number processed
   - Final message sent, then connection closes

4. **`failed`**: Job encountered an error
   - `progress`: Value at time of failure
   - `messages_processed`: Number processed before failure
   - `errors`: Array containing error message(s)
   - Final message sent, then connection closes

#### Error Handling

If a job doesn't exist, the WebSocket will:
1. Accept the connection
2. Send an error message:
   ```json
   {
       "error": "Job {job_id} not found",
       "job_id": "550e8400-e29b-41d4-a716-446655440000"
   }
   ```
3. Close the connection

#### Example Usage

**JavaScript:**
```javascript
// Connect to unified endpoint
const ws = new WebSocket('ws://localhost:8000/api/v1/jobs/ws/progress/550e8400-e29b-41d4-a716-446655440000');

ws.onmessage = (event) => {
    const data = JSON.parse(event.data);
    
    if (data.error) {
        console.error('Error:', data.error);
        return;
    }
    
    console.log(`Status: ${data.status}`);
    console.log(`Progress: ${data.progress}%`);
    console.log(`Processed: ${data.messages_processed} messages`);
    
    if (data.errors.length > 0) {
        console.warn('Errors:', data.errors);
    }
    
    // Check if job is complete
    if (data.status === 'completed' || data.status === 'failed') {
        console.log('Job finished:', data.status);
        ws.close();
    }
};

ws.onerror = (error) => {
    console.error('WebSocket error:', error);
};

ws.onclose = () => {
    console.log('WebSocket connection closed');
};
```

**Python:**
```python
import asyncio
import websockets
import json

async def monitor_job(job_id: str):
    uri = f"ws://localhost:8000/api/v1/jobs/ws/progress/{job_id}"
    
    async with websockets.connect(uri) as websocket:
        async for message in websocket:
            data = json.loads(message)
            
            if "error" in data:
                print(f"Error: {data['error']}")
                break
            
            print(f"Status: {data['status']}, Progress: {data['progress']}%")
            print(f"Processed: {data['messages_processed']} messages")
            
            if data['status'] in ['completed', 'failed']:
                print(f"Job finished: {data['status']}")
                break

# Usage
asyncio.run(monitor_job("550e8400-e29b-41d4-a716-446655440000"))
```

## Core Modules

### Data Storage

#### `postparse.core.data.database.SocialMediaDatabase`

The main database interface for storing and retrieving social media content and classification results.

**Constructor:**

```python
SocialMediaDatabase(db_path: str = "social_media.db")
```

**Parameters:**
- `db_path` (str): Path to SQLite database file. Default: `"social_media.db"`

**Example:**

```python
from backend.postparse.core.data.database import SocialMediaDatabase

db = SocialMediaDatabase("my_data.db")
```

**Methods:**

##### `get_instagram_posts(limit: int = None) -> List[Dict[str, Any]]`

Retrieve Instagram posts from the database.

**Parameters:**
- `limit` (int, optional): Maximum number of posts to return

**Returns:**
- List of dictionaries containing post data

**Example:**

```python
posts = db.get_instagram_posts(limit=10)
for post in posts:
    print(post['caption'])
```

##### `get_telegram_messages(limit: int = None) -> List[Dict[str, Any]]`

Retrieve Telegram messages from the database.

**Parameters:**
- `limit` (int, optional): Maximum number of messages to return

**Returns:**
- List of dictionaries containing message data

##### `get_posts_by_hashtag(hashtag: str) -> List[Dict[str, Any]]`

Search Instagram posts by hashtag.

**Parameters:**
- `hashtag` (str): Hashtag to search for (without # symbol)

**Returns:**
- List of matching posts

##### `get_posts_by_date_range(start_date: datetime, end_date: datetime) -> List[Dict[str, Any]]`

Get Instagram posts within a date range.

**Parameters:**
- `start_date` (datetime): Start of date range
- `end_date` (datetime): End of date range

**Returns:**
- List of posts within the date range

##### `post_exists(shortcode: str) -> bool`

Check if an Instagram post exists in the database.

**Parameters:**
- `shortcode` (str): Instagram post shortcode

**Returns:**
- `True` if post exists, `False` otherwise

##### `message_exists(message_id: int) -> bool`

Check if a Telegram message exists in the database.

**Parameters:**
- `message_id` (int): Telegram message ID

**Returns:**
- `True` if message exists, `False` otherwise

##### `save_classification_result(content_id, content_source, classifier_name, label, confidence, details=None, classification_type='single', run_id=None, reasoning=None, llm_metadata=None) -> int`

Save a classification result to the database.

**Parameters:**
- `content_id` (int): ID of the content (instagram_posts.id or telegram_messages.id)
- `content_source` (str): Source of content (`'instagram'` or `'telegram'`)
- `classifier_name` (str): Name of classifier (e.g., `'recipe_llm'`, `'multi_class_llm'`)
- `label` (str): Classification label
- `confidence` (float): Confidence score (0.0 to 1.0)
- `details` (dict, optional): Additional classification details (stored as key-value pairs)
- `classification_type` (str): Type of classification (`'single'` or `'multi_label'`)
- `run_id` (str, optional): UUID to group multi-label results
- `reasoning` (str, optional): LLM's reasoning for the classification
- `llm_metadata` (dict, optional): LLM configuration metadata (stored as JSON)

**Returns:**
- ID of the inserted `content_analysis` record

**Example:**

```python
db.save_classification_result(
    content_id=42,
    content_source='instagram',
    classifier_name='recipe_llm',
    label='recipe',
    confidence=0.95,
    details={'cuisine_type': 'italian', 'difficulty': 'easy'},
    reasoning='Contains cooking instructions and ingredient list',
    llm_metadata={'provider': 'lm_studio', 'model': 'qwen/qwen3-vl-8b'}
)
```

##### `get_classification_results(content_id, content_source, classifier_name=None, run_id=None) -> List[Dict]`

Retrieve classification results for content.

**Parameters:**
- `content_id` (int): ID of the content
- `content_source` (str): Source of content (`'instagram'` or `'telegram'`)
- `classifier_name` (str, optional): Filter by classifier name
- `run_id` (str, optional): Filter by run_id (for multi-label grouping)

**Returns:**
- List of classification result dictionaries with keys: `id`, `classifier_name`, `classification_type`, `run_id`, `label`, `confidence`, `reasoning`, `llm_metadata`, `analyzed_at`, `details`

**Example:**

```python
results = db.get_classification_results(42, 'instagram')
for r in results:
    print(f"{r['label']} ({r['confidence']:.0%})")
    if r['reasoning']:
        print(f"  Reasoning: {r['reasoning']}")
```

##### `has_classification(content_id, content_source, classifier_name) -> bool`

Check if content has been classified by a specific classifier.

**Parameters:**
- `content_id` (int): ID of the content
- `content_source` (str): Source of content (`'instagram'` or `'telegram'`)
- `classifier_name` (str): Name of classifier to check

**Returns:**
- `True` if classification exists, `False` otherwise

**Example:**

```python
if not db.has_classification(42, 'instagram', 'recipe_llm'):
    # Classify and save result
    result = classifier.predict(text)
    db.save_classification_result(...)
```

---

## Telegram Module

### `postparse.telegram.telegram_parser.TelegramParser`

Extracts saved messages from Telegram using the Telethon library.

**Constructor:**

```python
TelegramParser(
    api_id: str,
    api_hash: str,
    phone: str = None,
    session_file: str = "telegram_session",
    cache_dir: Optional[str] = None,
    downloads_dir: Optional[str] = None,
    config_path: Optional[str] = None
)
```

**Parameters:**
- `api_id` (str): Telegram API ID from [my.telegram.org](https://my.telegram.org)
- `api_hash` (str): Telegram API hash
- `phone` (str, optional): Phone number in international format (e.g., `+1234567890`)
- `session_file` (str): Name of session file. Default: `"telegram_session"`
- `cache_dir` (str, optional): Directory for cache files. Uses config default if None
- `downloads_dir` (str, optional): Directory for media downloads. Uses config default if None
- `config_path` (str, optional): Path to config file. Uses default locations if None

**Usage:**

Must be used as an async context manager:

```python
async with TelegramParser(api_id="...", api_hash="...") as parser:
    # Use parser methods here
    pass
```

**Methods:**

##### `async get_saved_messages(limit: Optional[int] = None, max_requests_per_session: Optional[int] = None, db: Optional[SocialMediaDatabase] = None, force_update: bool = False) -> AsyncGenerator[Dict[str, Any], None]`

Extract saved messages from Telegram.

**Parameters:**
- `limit` (int, optional): Maximum number of messages to extract
- `max_requests_per_session` (int, optional): Max API requests per session
- `db` (SocialMediaDatabase, optional): Database to check for existing messages
- `force_update` (bool): If True, fetch all messages regardless of database state

**Yields:**
- Dictionary containing message data with keys: `message_id`, `chat_id`, `content`, `content_type`, `media_urls`, `views`, `forwards`, `reply_to_msg_id`, `created_at`, `hashtags`

**Example:**

```python
async with TelegramParser(api_id="...", api_hash="...") as parser:
    async for message in parser.get_saved_messages(limit=100):
        print(f"Message: {message['content']}")
```

##### `async save_messages_to_db(db: SocialMediaDatabase, limit: Optional[int] = None, max_requests_per_session: Optional[int] = None, force_update: bool = False) -> int`

Save Telegram messages directly to database.

**Parameters:**
- `db` (SocialMediaDatabase): Database instance
- `limit` (int, optional): Maximum number of messages to save
- `max_requests_per_session` (int, optional): Max API requests per session
- `force_update` (bool): Update existing messages if True

**Returns:**
- Number of messages saved

### `postparse.telegram.telegram_parser.save_telegram_messages`

Helper function to save Telegram messages without dealing with async code.

**Signature:**

```python
save_telegram_messages(
    api_id: str,
    api_hash: str,
    phone: str = None,
    db_path: Optional[str] = None,
    session_file: str = "telegram_session",
    cache_dir: Optional[str] = None,
    downloads_dir: Optional[str] = None,
    limit: Optional[int] = None,
    max_requests_per_session: Optional[int] = None,
    force_update: bool = False,
    config_path: Optional[str] = None
) -> int
```

**Parameters:**
- Same as `TelegramParser` constructor plus `db_path` for database location

**Returns:**
- Number of messages saved

**Example:**

```python
from backend.postparse.services.parsers.telegram.telegram_parser import save_telegram_messages

count = save_telegram_messages(
    api_id="your_api_id",
    api_hash="your_api_hash",
    phone="+1234567890",
    limit=100
)
print(f"Saved {count} messages")
```

---

## Instagram Module

### `postparse.instagram.instagram_parser.InstaloaderParser`

Extracts saved posts from Instagram using Instaloader.

**Constructor:**

```python
InstaloaderParser(
    username: str,
    password: str,
    session_file: str = "instagram_session",
    max_retries: Optional[int] = None,
    min_delay: Optional[float] = None,
    max_delay: Optional[float] = None,
    config_path: Optional[str] = None
)
```

**Parameters:**
- `username` (str): Instagram username
- `password` (str): Instagram password
- `session_file` (str): Name of session file for caching login
- `max_retries` (int, optional): Max retry attempts for rate-limited requests
- `min_delay` (float, optional): Minimum delay between requests in seconds
- `max_delay` (float, optional): Maximum delay between requests in seconds
- `config_path` (str, optional): Path to config file

**Methods:**

##### `get_saved_posts(limit: Optional[int] = None, db: Optional[SocialMediaDatabase] = None, force_update: bool = False) -> Generator[Dict[str, Any], None, None]`

Extract saved posts from Instagram.

**Parameters:**
- `limit` (int, optional): Maximum number of posts to extract
- `db` (SocialMediaDatabase, optional): Database to check for existing posts
- `force_update` (bool): Fetch all posts regardless of database state

**Yields:**
- Dictionary containing post data with keys: `shortcode`, `owner_username`, `owner_id`, `caption`, `is_video`, `url`, `typename`, `likes`, `comments`, `created_at`, `hashtags`, `mentions`

##### `save_posts_to_db(db: SocialMediaDatabase, limit: Optional[int] = None, force_update: bool = False, batch_size: int = 100) -> int`

Save Instagram posts to database with batch optimization.

**Parameters:**
- `db` (SocialMediaDatabase): Database instance
- `limit` (int, optional): Maximum number of posts to save
- `force_update` (bool): Update existing posts if True
- `batch_size` (int): Number of posts to process per batch. Default: 100

**Returns:**
- Number of posts saved

**Example:**

```python
from backend.postparse.services.parsers.instagram.instagram_parser import InstaloaderParser
from backend.postparse.core.data.database import SocialMediaDatabase

db = SocialMediaDatabase()
parser = InstaloaderParser(username="user", password="pass")
count = parser.save_posts_to_db(db, limit=50)
```

### `postparse.instagram.instagram_parser.InstagramAPIParser`

Alternative parser using Instagram Platform API (for Business accounts).

**Constructor:**

```python
InstagramAPIParser(access_token: str, user_id: str)
```

**Parameters:**
- `access_token` (str): Instagram Graph API access token
- `user_id` (str): Instagram Business Account ID

**Methods:**

Same as `InstaloaderParser`: `get_saved_posts()` and `save_posts_to_db()`

---

## Analysis Module

### Classifiers

#### `backend.postparse.services.analysis.classifiers.llm.RecipeLLMClassifier`

Advanced LLM-based recipe classifier with detailed analysis using LangChain.

**Constructor:**

```python
RecipeLLMClassifier(
    provider_name: Optional[str] = None,
    config_path: Optional[str] = None
)
```

**Parameters:**
- `provider_name` (str, optional): Name of LLM provider to use (e.g., 'ollama', 'openai', 'lm_studio'). Uses config default if None
- `config_path` (str, optional): Path to config file

**Methods:**

##### `predict(text: str) -> ClassificationResult`

Predict if content is a recipe and extract details.

**Parameters:**
- `text` (str): Content to analyze

**Returns:**
- `ClassificationResult` object with fields:
  - `label` (str): `"recipe"` or `"not_recipe"`
  - `confidence` (float): Confidence score (0.0 to 1.0)
  - `details` (dict): Additional details including `cuisine_type`, `difficulty`, `meal_type`, `ingredients_count`

**Example:**

```python
from backend.postparse.services.analysis.classifiers.llm import RecipeLLMClassifier

classifier = RecipeLLMClassifier()
result = classifier.predict("Spaghetti Carbonara recipe...")
print(f"Label: {result.label}, Confidence: {result.confidence}")
print(f"Details: {result.details}")
```

#### `postparse.analysis.classifiers.base.BaseClassifier`

Abstract base class for all classifiers. Use this to create custom classifiers.

**Abstract Methods:**

- `fit(X: Any, y: Optional[Any] = None) -> BaseClassifier`: Fit the classifier
- `predict(X: Any) -> ClassificationResult`: Make predictions

**Concrete Methods:**

- `predict_batch(X: list[Any]) -> list[ClassificationResult]`: Batch predictions

---

## Configuration Module

### `postparse.utils.config.ConfigManager`

Manages application configuration from TOML files with environment variable overrides.

**Constructor:**

```python
ConfigManager(config_path: Optional[Union[str, Path]] = None)
```

**Parameters:**
- `config_path` (str or Path, optional): Path to config file. Searches standard locations if None

**Methods:**

##### `get(key_path: str, default: Any = None, env_var: Optional[str] = None) -> Any`

Get configuration value with support for nested keys and environment overrides.

**Parameters:**
- `key_path` (str): Dot-separated path to config key (e.g., `"models.zero_shot_model"`)
- `default` (Any, optional): Default value if key not found
- `env_var` (str, optional): Environment variable name to check for override

**Returns:**
- Configuration value or default

**Example:**

```python
from backend.postparse.core.utils.config import ConfigManager

config = ConfigManager()
model = config.get('models.zero_shot_model', default='llama2')
timeout = config.get('models.timeout', default=30, env_var='MODEL_TIMEOUT')
```

##### `get_section(section: str) -> Dict[str, Any]`

Get entire configuration section.

**Parameters:**
- `section` (str): Name of configuration section

**Returns:**
- Dictionary containing section data

### Convenience Functions

#### `get_config(config_path: Optional[Union[str, Path]] = None) -> ConfigManager`

Get global configuration manager instance (cached).

#### `get_model_config() -> Dict[str, Any]`

Get model configuration section.

#### `get_classification_config() -> Dict[str, Any]`

Get classification configuration section.

#### `get_database_config() -> Dict[str, Any]`

Get database configuration section.

#### `get_api_config() -> Dict[str, Any]`

Get API configuration section.

#### `get_paths_config() -> Dict[str, Any]`

Get paths configuration section.

**Example:**

```python
from backend.postparse.core.utils.config import get_model_config, get_database_config

model_config = get_model_config()
print(model_config['zero_shot_model'])

db_config = get_database_config()
print(db_config['default_db_path'])
```

---

## Data Models

### `postparse.analysis.classifiers.base.ClassificationResult`

Pydantic model for classification results.

**Fields:**
- `label` (str): Classification label
- `confidence` (float): Confidence score (0.0 to 1.0)
- `details` (dict, optional): Additional classification details

**Example:**

```python
from backend.postparse.services.analysis.classifiers.base import ClassificationResult

result = ClassificationResult(
    label="recipe",
    confidence=0.95,
    details={"cuisine": "Italian"}
)
```

---

## Error Handling

### Instagram Exceptions

#### `InstagramRateLimitError`

Raised when Instagram rate limits are hit. Inherits from `Exception`.

#### `InstagramAPIError`

Raised when Instagram API encounters an error. Inherits from `Exception`.

**Example:**

```python
from backend.postparse.services.parsers.instagram.instagram_parser import InstaloaderParser, InstagramRateLimitError

try:
    parser = InstaloaderParser(username="user", password="pass")
    posts = list(parser.get_saved_posts())
except InstagramRateLimitError as e:
    print(f"Rate limited: {e}")
    # Wait and retry
```

---

## Notes on Stability

- **Stable**: Core parsing (Telegram, Instagram), database operations, configuration
- **Stable**: `RecipeLLMClassifier` for recipe detection using LLM providers
- **Stable**: `MultiClassLLMClassifier` for custom category classification
- **Internal**: Any modules not documented here are internal implementation details and may change without notice

**Note:** `RecipeLLMClassifier` is the primary and only recipe classifier. It supports all LLM providers (Ollama, LM Studio, OpenAI, Anthropic, etc.) configured in `config.toml`. There is no separate basic classifier - all classification uses LLM-based approaches.

