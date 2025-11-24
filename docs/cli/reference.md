# CLI Command Reference

Complete reference for all PostParse CLI commands and options.

> **See Also:** [Getting Started](getting_started.md) | [Cookbook](cookbook.md) | [CLI Index](index.md)

## Global Options

Available for all commands:

| Option | Description |
|--------|-------------|
| `--config PATH` | Custom config file path |
| `--verbose` | Enable verbose output |
| `--quiet` | Suppress non-essential output |
| `--version` | Show version and exit |
| `--help` | Show help message |

## Commands

### Core Commands

Quick access commands for common operations.

#### `postparse stats`

Show database statistics (shortcut for `postparse db stats`).

**Options:**

| Option | Type | Default | Description |
|--------|------|---------|-------------|
| `--detailed` | Flag | False | Include hashtag distribution |

**Examples:**

```bash
# Quick database overview
postparse stats

# Detailed statistics with hashtags
postparse stats --detailed
```

**Output:**

Shows a summary panel with:
- Total Instagram posts and Telegram messages
- Date ranges for each platform
- Content/media type breakdowns
- Top 20 hashtags (with --detailed)

If database is empty, displays helpful getting started guide.

#### `postparse info`

Show system information and installed packages.

**Examples:**

```bash
# View installation details
postparse info
```

**Output:**

Displays:
- PostParse version
- Python version
- Installed package versions (Click, Rich, Telethon, Instaloader, FastAPI)
- Available commands summary

### Extract Commands

Extract data from social media platforms.

#### `postparse extract telegram`

Extract Telegram messages from your **Saved Messages** folder.

> **Important:** Only extracts from Saved Messages (not channels, groups, or direct chats).

**Options:**

| Option | Type | Required | Description |
|--------|------|----------|-------------|
| `--api-id` | Text | Yes* | Telegram API ID |
| `--api-hash` | Text | Yes* | Telegram API hash |
| `--phone` | Text | No | Phone number (prompted if needed) |
| `--session` | Text | No | Session file name (default: telegram_session) |
| `--limit` | Integer | No | Maximum messages to extract |
| `--force` | Flag | No | Force re-fetch existing messages |

*Can be provided via environment variables `TELEGRAM_API_ID` and `TELEGRAM_API_HASH`

**What Gets Extracted:**
- Messages from "Saved Messages" folder only
- Text content, captions, and media URLs
- Hashtags, mentions, and metadata
- View counts and forward info

**Examples:**

```bash
# Check for new messages first (recommended)
postparse check telegram

# Basic extraction with API credentials
postparse extract telegram --api-id 12345678 --api-hash abc123def456

# Extract limited messages
postparse extract telegram --api-id 12345678 --api-hash abc123def456 --limit 100

# Force re-fetch existing messages
postparse extract telegram --api-id 12345678 --api-hash abc123def456 --force

# Using environment variables
export TELEGRAM_API_ID=12345678
export TELEGRAM_API_HASH=abc123def456
postparse extract telegram

# Custom session file
postparse extract telegram --api-id 12345678 --api-hash abc123def456 --session my_session
```

**Output:**

Shows connection, progress with delays, and summary:

```
ℹ Connecting to Telegram...
✓ Connected to Telegram!
ℹ Extracting messages from Saved Messages...

Sampling 20 newest messages (limit: 20)...
Checking messages: 100%|████| 20/20 [02:30<00:00]

✓ Extraction completed!

┏━━━━━━━━━━━━━━━━┳━━━━━━━┓
┃ Metric         ┃ Count ┃
┡━━━━━━━━━━━━━━━━╇━━━━━━━┩
│ Messages saved │    15 │
└────────────────┴───────┘
```

**Note:** Only new messages are saved. Existing messages are automatically skipped.

**Troubleshooting:**

- **Authentication errors**: Ensure API credentials are correct from https://my.telegram.org
- **First-time setup**: You'll be prompted for phone verification code and 2FA password
- **Session errors**: Delete the session file and re-authenticate
- **Rate limiting**: Telegram enforces delays (2-7s per message) to prevent bans
- **Slow extraction**: Normal! Delays are intentional. Use `--limit` for testing
- **Empty Saved Messages**: Make sure you have messages saved in Telegram's "Saved Messages" folder

#### `postparse extract instagram`

Extract Instagram posts from your saved posts.

**Options:**

| Option | Type | Required | Description |
|--------|------|----------|-------------|
| `--username` | Text | Yes* | Instagram username |
| `--password` | Text | Yes* | Instagram password |
| `--session` | Text | No | Session file name (default: instagram_session) |
| `--limit` | Integer | No | Maximum posts to extract |
| `--force` | Flag | No | Force re-fetch existing posts |

*Can be provided via environment variables `INSTAGRAM_USERNAME` and `INSTAGRAM_PASSWORD`

**Examples:**

```bash
# Basic extraction
postparse extract instagram --username myuser --password mypass

# Extract limited posts
postparse extract instagram --username myuser --password mypass --limit 50

# Using environment variables
export INSTAGRAM_USERNAME=myuser
export INSTAGRAM_PASSWORD=mypass
postparse extract instagram

# Force re-fetch
postparse extract instagram --force
```

**Output:**

Similar to Telegram extraction, displays progress and summary:

```
ℹ Initializing Instagram parser...
ℹ Logging in to Instagram...
✓ Logged in to Instagram!
ℹ Extracting saved posts...
[Progress bar]
✓ Extraction completed!

┏━━━━━━━━━━━━━━━━━━━━━┳━━━━━━━┓
┃ Metric              ┃ Count ┃
┡━━━━━━━━━━━━━━━━━━━━━╇━━━━━━━┩
│ Total processed     │    75 │
│ New posts           │    60 │
│ Skipped (existing)  │    15 │
│ Errors              │     0 │
└─────────────────────┴───────┘
```

**Troubleshooting:**

- **Login errors**: Check username/password, enable "Allow apps to access your account"
- **Rate limiting**: Instagram aggressively rate-limits; extraction may be slow
- **2FA**: Two-factor authentication is supported; follow prompts
- **Session expired**: Delete session file and re-login

### Classify Commands

Classify content using ML/LLM models.

#### `postparse classify single`

Classify a single text as recipe or not.

**Arguments:**

| Argument | Type | Required | Description |
|----------|------|----------|-------------|
| `text` | Text | Yes* | Text to classify (or `-` for stdin) |

*Can be piped from stdin

**Options:**

| Option | Type | Default | Description |
|--------|------|---------|-------------|
| `--provider` | Text | From config | LLM provider to use |
| `--detailed` | Flag | False | Use detailed LLM classifier |
| `--output` | Choice | text | Output format (text/json) |

**Examples:**

```bash
# Classify direct text
postparse classify single "Mix flour and water to make dough"

# Classify from stdin
echo "Boil pasta for 10 minutes" | postparse classify single -

# Use detailed LLM classifier
postparse classify single --detailed "Preheat oven to 350°F..."

# Specify LLM provider
postparse classify single --provider openai --detailed "Recipe text..."

# JSON output for scripting
postparse classify single --output json "Mix ingredients" | jq .
```

**Output (text format):**

```
ℹ Initializing simple classifier...
ℹ Classifying text...

╭─────── Classification Result ───────╮
│ Label: recipe                       │
│ Confidence: 92.50%                  │
╰─────────────────────────────────────╯
```

**Output (JSON format):**

```json
{
  "label": "recipe",
  "confidence": 0.925,
  "details": {
    "has_ingredients": true,
    "has_instructions": true,
    "cooking_verbs": ["mix", "boil", "bake"]
  }
}
```

**Troubleshooting:**

- **LLM errors**: Ensure provider is configured in config.toml
- **Low confidence**: Try `--detailed` for better accuracy
- **Slow response**: LLM classification takes longer than simple classifier

#### `postparse classify batch`

Classify multiple items from the database.

**Options:**

| Option | Type | Default | Description |
|--------|------|---------|-------------|
| `--source` | Choice | posts | Source to classify (posts/messages) |
| `--limit` | Integer | None | Maximum items to classify |
| `--filter-hashtag` | Text | None | Filter by hashtag (multiple allowed) |
| `--provider` | Text | From config | LLM provider to use |
| `--detailed` | Flag | False | Use detailed LLM classifier |

**Examples:**

```bash
# Classify all posts
postparse classify batch --source posts

# Classify limited items
postparse classify batch --source messages --limit 100

# Filter by hashtag
postparse classify batch --filter-hashtag recipe

# Multiple hashtag filters
postparse classify batch --filter-hashtag recipe --filter-hashtag cooking

# Use detailed classifier
postparse classify batch --detailed --provider ollama
```

**Output:**

```
ℹ Initializing simple classifier...
ℹ Querying posts from database...
ℹ Found 150 posts to classify
[Progress bar]
✓ Classification completed!

┏━━━━━━┳━━━━━━━━━━━━━━━━━━┳━━━━━━━━━━┳━━━━━━━━━━━━┓
┃ ID   ┃ Content Preview  ┃ Label    ┃ Confidence ┃
┡━━━━━━╇━━━━━━━━━━━━━━━━━━╇━━━━━━━━━━╇━━━━━━━━━━━━┩
│ 1    │ Mix flour and... │ recipe   │     95.20% │
│ 2    │ Beautiful suns...│ not_rec..│     78.40% │
│ ...  │ ...              │ ...      │        ... │
└──────┴──────────────────┴──────────┴────────────┘

ℹ Showing first 20 of 150 results

┏━━━━━━━━━━━━━━━━━━┳━━━━━━━━┓
┃ Metric           ┃  Value ┃
┡━━━━━━━━━━━━━━━━━━╇━━━━━━━━┩
│ Total classified │    150 │
│ Recipe           │     89 │
│ Not recipe       │     61 │
│ Avg confidence   │ 87.35% │
└──────────────────┴────────┘
```

### Search Commands

Search stored posts and messages.

#### `postparse search posts`

Search Instagram posts with filters.

**Options:**

| Option | Type | Default | Description |
|--------|------|---------|-------------|
| `--hashtag` | Text | None | Filter by hashtag (multiple allowed) |
| `--username` | Text | None | Filter by owner username |
| `--type` | Choice | None | Content type (image/video) |
| `--from` | Date | None | Start date (YYYY-MM-DD) |
| `--to` | Date | None | End date (YYYY-MM-DD) |
| `--limit` | Integer | 50 | Maximum results |
| `--output` | Choice | table | Output format (table/json) |

**Examples:**

```bash
# Search all posts
postparse search posts

# Filter by hashtag
postparse search posts --hashtag recipe

# Multiple hashtags (AND logic)
postparse search posts --hashtag recipe --hashtag cooking

# Filter by content type
postparse search posts --hashtag recipe --type video

# Date range filter
postparse search posts --from 2024-01-01 --to 2024-12-31

# Filter by username
postparse search posts --username chef_john

# Custom limit
postparse search posts --hashtag recipe --limit 100

# JSON output for scripting
postparse search posts --output json | jq '.[] | .caption'
```

**Output (table format):**

```
ℹ Searching with filters: hashtags: recipe; type: video
✓ Found 25 post(s)

┏━━━━━━┳━━━━━━━━━━┳━━━━━━━━━━━━━━━━━━━━━┳━━━━━━━┳━━━━━━━┳━━━━━━━━━━━━┓
┃ ID   ┃ Username ┃ Caption Preview     ┃ Type  ┃ Likes ┃       Date ┃
┡━━━━━━╇━━━━━━━━━━╇━━━━━━━━━━━━━━━━━━━━━╇━━━━━━━╇━━━━━━━╇━━━━━━━━━━━━┩
│ 101  │ chef_jo..│ Easy pasta recipe...│ video │  1250 │ 2024-11-15 │
│ 102  │ cooking..│ Quick dinner idea...│ video │   890 │ 2024-11-10 │
│ ...  │ ...      │ ...                 │ ...   │   ... │        ... │
└──────┴──────────┴─────────────────────┴───────┴───────┴────────────┘

ℹ Showing first 50 results. Use --limit to see more.
```

#### `postparse search messages`

Search Telegram messages with filters.

**Options:**

| Option | Type | Default | Description |
|--------|------|---------|-------------|
| `--hashtag` | Text | None | Filter by hashtag (multiple allowed) |
| `--type` | Choice | None | Content type (text/photo/video) |
| `--from` | Date | None | Start date (YYYY-MM-DD) |
| `--to` | Date | None | End date (YYYY-MM-DD) |
| `--limit` | Integer | 50 | Maximum results |
| `--output` | Choice | table | Output format (table/json) |

**Examples:**

```bash
# Search all messages
postparse search messages

# Filter by hashtag
postparse search messages --hashtag recipe

# Filter by media type
postparse search messages --type photo

# Date range
postparse search messages --from 2024-01-01 --to 2024-06-30

# Combined filters
postparse search messages --hashtag recipe --type photo --limit 100
```

**Output:**

```
ℹ Searching with filters: hashtags: recipe
✓ Found 45 message(s)

┏━━━━━━┳━━━━━━━━━━━━━━━━━━━━━━━━━━━┳━━━━━━━┳━━━━━━━┳━━━━━━━━━━━━┓
┃ ID   ┃ Content Preview           ┃  Type ┃ Views ┃       Date ┃
┡━━━━━━╇━━━━━━━━━━━━━━━━━━━━━━━━━━━╇━━━━━━━╇━━━━━━━╇━━━━━━━━━━━━┩
│ 1001 │ Amazing chocolate cake... │ photo │   523 │ 2024-11-20 │
│ 1002 │ Quick breakfast recipe... │  text │   412 │ 2024-11-18 │
│ ...  │ ...                       │   ... │   ... │        ... │
└──────┴───────────────────────────┴───────┴───────┴────────────┘
```

### Serve Command

Start the FastAPI server.

#### `postparse serve`

Start the PostParse API server using Uvicorn.

**Options:**

| Option | Type | Default | Description |
|--------|------|---------|-------------|
| `--host` | Text | 0.0.0.0 | Host to bind |
| `--port` | Integer | 8000 | Port to bind |
| `--reload` | Flag | False | Enable auto-reload |
| `--workers` | Integer | 1 | Number of workers |
| `--log-level` | Choice | info | Log level (debug/info/warning/error) |

**Examples:**

```bash
# Start with defaults
postparse serve

# Custom port
postparse serve --port 8080

# Development mode with auto-reload
postparse serve --reload

# Production mode with multiple workers
postparse serve --workers 4

# Debug mode
postparse serve --log-level debug --reload

# Custom host and port
postparse serve --host 127.0.0.1 --port 5000
```

**Output:**

```
╭───────────── PostParse API Server ─────────────╮
│ PostParse API Server                           │
│                                                │
│ Server URL: http://0.0.0.0:8000               │
│ API Documentation: http://0.0.0.0:8000/docs   │
│ ReDoc: http://0.0.0.0:8000/redoc              │
│                                                │
│ Configuration:                                 │
│   • Workers: 1                                 │
│   • Auto-reload: No                            │
│   • Log level: info                            │
│   • Auth enabled: False                        │
│   • Rate limiting: False                       │
│                                                │
│ Press Ctrl+C to stop the server                │
╰────────────────────────────────────────────────╯

INFO: Started server process [12345]
INFO: Waiting for application startup.
INFO: Application startup complete.
INFO: Uvicorn running on http://0.0.0.0:8000
```

**Accessing the API:**

Once running, access:

- **Swagger UI**: http://localhost:8000/docs
- **ReDoc**: http://localhost:8000/redoc
- **OpenAPI JSON**: http://localhost:8000/openapi.json

**Production Tips:**

- Use `--workers 4` (or number of CPU cores) for better performance
- Don't use `--reload` in production (slower performance)
- Set `--log-level warning` or `error` in production
- Use a reverse proxy (nginx, Caddy) for HTTPS

### Database Commands

Database operations and statistics.

#### `postparse db stats`

Show database statistics.

**Options:**

| Option | Type | Default | Description |
|--------|------|---------|-------------|
| `--detailed` | Flag | False | Show detailed stats including hashtag distribution |

**Examples:**

```bash
# Basic statistics
postparse db stats

# Detailed statistics with hashtags
postparse db stats --detailed
```

**Output:**

```
ℹ Computing database statistics...

╭──────────── Database Overview ────────────╮
│ Database Overview                         │
│                                           │
│ Instagram Posts: 250                      │
│ Telegram Messages: 450                    │
│ Total Items: 700                          │
│                                           │
│ Instagram Date Range:                     │
│   • Oldest: 2024-01-15                    │
│   • Newest: 2024-11-23                    │
│                                           │
│ Telegram Date Range:                      │
│   • Oldest: 2024-02-01                    │
│   • Newest: 2024-11-22                    │
│                                           │
│ Instagram Content Types:                  │
│   • image: 180                            │
│   • video: 70                             │
│                                           │
│ Telegram Media Types:                     │
│   • text: 320                             │
│   • photo: 95                             │
│   • video: 35                             │
╰───────────────────────────────────────────╯

✓ Statistics computed successfully!
```

**With `--detailed`:**

```
[Above output plus:]

┏━━━━━━┳━━━━━━━━━━━━━━━┳━━━━━━━┓
┃ Rank ┃ Hashtag       ┃ Count ┃
┡━━━━━━╇━━━━━━━━━━━━━━━╇━━━━━━━┩
│    1 │ recipe        │   125 │
│    2 │ cooking       │    89 │
│    3 │ food          │    76 │
│    4 │ baking        │    45 │
│  ... │ ...           │   ... │
└──────┴───────────────┴───────┘
```

#### `postparse db export`

Export database to file.

**Arguments:**

| Argument | Type | Required | Description |
|----------|------|----------|-------------|
| `output` | Path | Yes | Output file path |

**Options:**

| Option | Type | Default | Description |
|--------|------|---------|-------------|
| `--format` | Choice | json | Export format (json/csv) |
| `--source` | Choice | all | What to export (posts/messages/all) |
| `--limit` | Integer | None | Maximum records to export |

**Examples:**

```bash
# Export all data to JSON
postparse db export data.json

# Export only posts
postparse db export posts.json --source posts

# Export to CSV
postparse db export data.csv --format csv

# Export limited records
postparse db export recent.json --limit 1000

# Export only messages
postparse db export messages.json --source messages --limit 500
```

**Output:**

```
ℹ Exporting data to data.json...
ℹ Fetching Instagram posts...
✓ Fetched 250 Instagram posts
ℹ Fetching Telegram messages...
✓ Fetched 450 Telegram messages
ℹ Writing to data.json...
✓ Export completed! 700 records written to data.json
```

**CSV Export Note:**

When exporting to CSV with `--source all`, separate files are created:

```bash
postparse db export data.csv --format csv

# Creates:
# - data_posts.csv (Instagram posts)
# - data_messages.csv (Telegram messages)
```

### Config Commands

Configuration management.

#### `postparse config show`

Display current configuration.

**Options:**

| Option | Type | Default | Description |
|--------|------|---------|-------------|
| `--section` | Choice | None | Show specific section (llm/api/database/telegram/instagram) |
| `--format` | Choice | text | Output format (text/json) |

**Examples:**

```bash
# Show all configuration
postparse config show

# Show specific section
postparse config show --section llm

# JSON output
postparse config show --format json

# Show API config
postparse config show --section api
```

**Output:**

```
ℹ Configuration file: config/config.toml

╭──────────── Configuration ────────────╮
│ {                                     │
│   "llm": {                            │
│     "providers": [                    │
│       {                               │
│         "name": "ollama",             │
│         "base_url": "http://loca...  │
│         "api_key": null,              │
│         "model_name": "llama3.2"     │
│       }                               │
│     ]                                 │
│   },                                  │
│   "api": {                            │
│     "host": "0.0.0.0",               │
│     "port": 8000,                     │
│     "reload": false,                  │
│     ...                               │
│   }                                   │
│ }                                     │
╰───────────────────────────────────────╯
```

**Note:** Sensitive values (API keys, passwords) are masked with `***` for security.

#### `postparse config validate`

Validate configuration file.

**Options:**

| Option | Type | Default | Description |
|--------|------|---------|-------------|
| `--fix` | Flag | False | Attempt to fix common issues |

**Examples:**

```bash
# Validate configuration
postparse config validate

# Validate and fix issues
postparse config validate --fix
```

**Output:**

```
┏━━━━━━━━━━━━━━━━━━━━━━━┳━━━━━━━━━━━┳━━━━━━━━━━━━━━━━━━━━━━━━━┓
┃ Check                 ┃ Status    ┃ Details                 ┃
┡━━━━━━━━━━━━━━━━━━━━━━━╇━━━━━━━━━━━╇━━━━━━━━━━━━━━━━━━━━━━━━━┩
│ Config file exists    │ ✓ Pass    │ Found at config/con...  │
│ Database directory    │ ✓ Pass    │ data exists             │
│ LLM providers         │ ✓ Pass    │ 1 provider(s) config... │
│ Provider ollama       │ ✓ Pass    │ Configured at http:...  │
│ API port              │ ✓ Pass    │ Port 8000 is valid      │
│ Directory sessions    │ ⚠ Warning │ Does not exist. Use ... │
│ Directory data        │ ✓ Pass    │ Exists                  │
│ Directory logs        │ ⚠ Warning │ Does not exist. Use ... │
└───────────────────────┴───────────┴─────────────────────────┘

⚠ Validation completed with warnings: 5 passed, 2 warnings
```

**With `--fix`:**

```
[Similar output, but warnings for missing directories become Pass]

✓ Validation passed: 7 checks passed
```

---

**For practical examples and workflows, see [Cookbook](cookbook.md)**

## Environment Variables

| Variable | Used By |
|----------|---------|
| `TELEGRAM_API_ID` | Telegram extraction |
| `TELEGRAM_API_HASH` | Telegram extraction |
| `TELEGRAM_PHONE` | Telegram extraction |
| `INSTAGRAM_USERNAME` | Instagram extraction |
| `INSTAGRAM_PASSWORD` | Instagram extraction |
| `OPENAI_API_KEY` | OpenAI LLM provider |
| `ANTHROPIC_API_KEY` | Anthropic LLM provider |

## Configuration

### Priority Order

1. CLI options (highest)
2. Environment variables
3. Config file
4. Defaults (lowest)

### Config File

Default locations:
- `config/config.toml` (recommended)
- `config.toml`
- Custom via `--config`

**Minimal config.toml:**

```toml
[database]
default_db_path = "data/social_media.db"

[llm]
default_provider = "lm_studio"

[[llm.providers]]
name = "lm_studio"
model = "qwen/qwen3-vl-8b"
api_base = "http://localhost:1234/v1"
```

---

**Version:** 0.1.0 | **Last Updated:** November 23, 2025

**See Also:**
- [Getting Started](getting_started.md) - Setup and first steps
- [Cookbook](cookbook.md) - Practical examples and workflows
- [Main Documentation](../index.md) - Full PostParse documentation

