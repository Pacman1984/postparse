# PostParse CLI Reference

Complete command-line interface reference for PostParse.

## Global Options

Available for all commands:

| Option | Description |
|--------|-------------|
| `--config PATH` | Path to custom config file |
| `--verbose` | Enable verbose output |
| `--quiet` | Suppress non-essential output |
| `--version` | Show version and exit |
| `--help` | Show help message |

## Core Commands

### `postparse stats`

Show database statistics (alias for `postparse db stats`).

**Options:**
- `--detailed` - Include hashtag distribution

**Examples:**
```bash
postparse stats
postparse stats --detailed
```

### `postparse info`

Show installation and version information.

**Examples:**
```bash
postparse info
```

### `postparse check`

Check for new content without downloading (fast preview).

**Subcommands:**
- `telegram` - Check Telegram for new messages
- `instagram` - Check Instagram for new posts
- `all` - Check both platforms (default)

**Options (telegram):**
- `--api-id` - Telegram API ID (required, or `TELEGRAM_API_ID` env var)
- `--api-hash` - Telegram API hash (required, or `TELEGRAM_API_HASH` env var)
- `--phone` - Phone number (or `TELEGRAM_PHONE` env var)
- `--session` - Session file name (default: `telegram_session`)

**Options (instagram):**
- `--username` - Instagram username (required, or `INSTAGRAM_USERNAME` env var)
- `--password` - Instagram password (required, or `INSTAGRAM_PASSWORD` env var)
- `--session` - Session file name (default: `instagram_session`)

**Examples:**
```bash
postparse check                    # Check all platforms
postparse check telegram           # Check Telegram only
postparse check instagram          # Check Instagram only
postparse check all                # Explicitly check all
```

## Data Operations

### `postparse extract`

Extract data from social media platforms.

**Subcommands:**
- `all` - Extract from both platforms (default)
- `telegram` - Extract from Telegram Saved Messages
- `instagram` - Extract Instagram saved posts

**Options (all):**
- `--limit` - Maximum items to extract per platform
- `--force` - Force re-fetch existing items

**Options (telegram):**
- `--api-id` - Telegram API ID (required, or `TELEGRAM_API_ID` env var)
- `--api-hash` - Telegram API hash (required, or `TELEGRAM_API_HASH` env var)
- `--phone` - Phone number (or `TELEGRAM_PHONE` env var)
- `--session` - Session file name (default: `telegram_session`)
- `--limit` - Maximum messages to extract
- `--force` - Force re-fetch existing messages

**Options (instagram):**
- `--username` - Instagram username (required, or `INSTAGRAM_USERNAME` env var)
- `--password` - Instagram password (required, or `INSTAGRAM_PASSWORD` env var)
- `--session` - Session file name (default: `instagram_session`)
- `--limit` - Maximum posts to extract
- `--force` - Force re-fetch existing posts

**Examples:**
```bash
postparse extract                    # Extract from all platforms
postparse extract all                # Explicitly extract from all
postparse extract all --limit 100    # Limit items per platform
postparse extract telegram --api-id 12345 --api-hash abc123
postparse extract telegram --limit 100
postparse extract instagram --username myuser --password mypass
postparse extract instagram --limit 50
```

### `postparse classify`

Classify content using LLM classifiers.

**Subcommands:**
- `text` - Classify free-form text (ad-hoc, doesn't save to database)
- `db` - Classify database content and save results

**Classifiers:**
- `recipe` - Binary classification (recipe vs non-recipe)
- `multiclass` - Custom categories (requires --classes)

**Options (text):**
- `--classifier` - Classifier type: `recipe` or `multiclass` (default: `recipe`)
- `--classes` - For multiclass: class definitions as JSON or @file
- `--provider` - LLM provider to use (default: from config)
- `--output` - Output format: `text` or `json` (default: `text`)

**Options (db):**
- `--source` - Database source: `all`, `instagram`, or `telegram` (default: `all`)
- `--classifier` - Classifier type: `recipe` or `multiclass` (default: `recipe`)
- `--classes` - For multiclass: class definitions as JSON or @file
- `--limit` - Maximum items to classify
- `--filter-hashtag` - Filter by hashtag (can specify multiple)
- `--provider` - LLM provider to use (default: from config)

**Note:** The `db` command saves results to the database. Already classified items are automatically skipped.

**Examples:**
```bash
# Ad-hoc text classification
postparse classify text "Mix flour and water to make dough"
postparse classify text "Check out FastAPI!" --classifier multiclass \
  --classes '{"recipe": "Cooking", "tech": "Technology"}'
echo "Recipe text" | postparse classify text -

# Database classification (saves results)
postparse classify db --limit 100  # all content
postparse classify db --source instagram --limit 100  # Instagram only
postparse classify db --source telegram --provider openai  # Telegram only
postparse classify db --classifier multiclass \
  --classes '{"recipe": "Cooking", "tech": "Technology", "other": "Other"}'
```

### Multi-Class Classification

For multi-class classification, use the `--classifier multiclass` option with either `text` or `db` commands:

```bash
# Ad-hoc multi-class classification
postparse classify text "Check out this new FastAPI library!" \
  --classifier multiclass \
  --classes '{"recipe": "Cooking", "tech": "Technology", "other": "Other"}'

# Database multi-class classification (saves results)
postparse classify db --classifier multiclass \
  --classes '{"recipe": "Cooking", "tech": "Technology", "other": "Other"}'

# Load classes from file
postparse classify db --classifier multiclass --classes @classes.json
```

**Classes File Format:**

Create a JSON file with class definitions:

```json
{
  "recipe": "A text containing cooking instructions, ingredients, or recipe details",
  "tech_news": "Technology news, product launches, or software releases",
  "movie_review": "A text reviewing or discussing movies, films, or TV shows"
}
```

**Tips:**

1. **Class Descriptions**: Provide detailed descriptions for better accuracy
2. **Number of Classes**: Use 2-10 classes for best results
3. **Provider Selection**: Use OpenAI or Anthropic for best accuracy; Ollama/LM Studio for local/free inference

### `postparse search`

Search stored posts and messages with filters.

**Subcommands:**
- `posts` - Search Instagram posts
- `messages` - Search Telegram messages

**Options (posts):**
- `--hashtag` - Filter by hashtag (can specify multiple)
- `--username` - Filter by owner username
- `--type` - Content type filter: `image` or `video`
- `--from` - Start date (YYYY-MM-DD)
- `--to` - End date (YYYY-MM-DD)
- `--limit` - Maximum results (default: 50)
- `--output` - Output format: `table` or `json` (default: `table`)

**Options (messages):**
- `--hashtag` - Filter by hashtag (can specify multiple)
- `--type` - Content type filter: `text`, `photo`, or `video`
- `--from` - Start date (YYYY-MM-DD)
- `--to` - End date (YYYY-MM-DD)
- `--limit` - Maximum results (default: 50)
- `--output` - Output format: `table` or `json` (default: `table`)

**Examples:**
```bash
postparse search posts --hashtag recipe
postparse search posts --hashtag recipe --hashtag cooking --type video
postparse search posts --from 2024-01-01 --to 2024-12-31 --limit 100
postparse search messages --hashtag recipe
postparse search messages --type photo --from 2024-01-01
```

## System Commands

### `postparse serve`

Start the FastAPI server.

**Options:**
- `--host` - Host to bind (default: `0.0.0.0`)
- `--port` - Port to bind (default: `8000`)
- `--reload` - Enable auto-reload
- `--workers` - Number of workers
- `--log-level` - Log level: `debug`, `info`, `warning`, or `error`

**Examples:**
```bash
postparse serve
postparse serve --port 8080 --reload
postparse serve --workers 4 --log-level info
```

### `postparse db`

Database operations and statistics.

**Subcommands:**
- `stats` - Show database statistics
- `export` - Export database to JSON/CSV

**Options (stats):**
- `--detailed` - Include hashtag distribution

**Options (export):**
- `--format` - Export format: `json` or `csv` (default: `json`)
- `--source` - What to export: `posts`, `messages`, or `all` (default: `all`)
- `--limit` - Maximum records to export

**Examples:**
```bash
postparse db stats
postparse db stats --detailed
postparse db export data.json
postparse db export posts.csv --format csv --source posts --limit 1000
```

### `postparse config`

Configuration management.

**Subcommands:**
- `show` - Display current configuration
- `validate` - Validate configuration file
- `env` - Show loaded environment variables

**Options (show):**
- `--section` - Show specific section: `llm`, `api`, `database`, `telegram`, or `instagram`
- `--format` - Output format: `text` or `json` (default: `text`)

**Options (validate):**
- `--fix` - Auto-fix common issues

**Examples:**
```bash
postparse config show
postparse config show --section llm
postparse config show --format json
postparse config validate
postparse config validate --fix
postparse config env
```

## Quick Reference

### Common Workflows

**Check and extract:**
```bash
postparse check all
postparse extract all --limit 100
```

**Classify and search:**
```bash
postparse classify batch --source messages --detailed
postparse search messages --hashtag recipe
```

**Export and serve:**
```bash
postparse db export data.json --format json
postparse serve --port 8080 --reload
```

### Environment Variables

| Variable | Used By |
|----------|---------|
| `TELEGRAM_API_ID` | Telegram extraction/check |
| `TELEGRAM_API_HASH` | Telegram extraction/check |
| `TELEGRAM_PHONE` | Telegram extraction/check |
| `INSTAGRAM_USERNAME` | Instagram extraction/check |
| `INSTAGRAM_PASSWORD` | Instagram extraction/check |

### Getting Help

```bash
postparse --help                    # All commands
postparse COMMAND --help            # Specific command help
postparse COMMAND SUBCOMMAND --help # Subcommand help
postparse info                      # System information
```

---

**See Also:**
- [Getting Started](getting_started.md) - Installation and first steps
- [Cookbook](cookbook.md) - Practical examples and workflows
- [API Reference](api_reference.md) - REST API documentation

