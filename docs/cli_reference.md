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

Classify content as recipe/not recipe using ML or LLM, or into custom categories.

**Subcommands:**
- `single` - Classify a single text as recipe/not recipe (supports stdin)
- `batch` - Classify multiple items from database as recipe/not recipe
- `multi` - Classify a single text into custom categories
- `multi-batch` - Classify multiple texts into custom categories

**Options (single):**
- `--provider` - LLM provider to use (default: from config)
- `--detailed` - Use detailed LLM classifier
- `--output` - Output format: `text` or `json` (default: `text`)

**Options (batch):**
- `--source` - Source to classify: `posts` or `messages` (default: `posts`)
- `--limit` - Maximum items to classify
- `--filter-hashtag` - Filter by hashtag (can specify multiple)
- `--provider` - LLM provider to use (default: from config)
- `--detailed` - Use detailed LLM classifier

**Examples:**
```bash
postparse classify single "Mix flour and water to make dough"
echo "Recipe text" | postparse classify single -
postparse classify single --detailed --provider openai "Recipe text..."
postparse classify batch --source messages --limit 100
postparse classify batch --filter-hashtag recipe --detailed
```

### Multi-Class Classification

Classify text into custom categories using LLM-based classification.

#### `postparse classify multi`

Classify a single text into one of your custom categories.

**Usage:**
```bash
postparse classify multi TEXT [OPTIONS]
```

**Arguments:**
- `TEXT`: Text to classify (required)

**Options:**
- `--classes TEXT`: Class definitions as JSON string or file path (prefix with @)
  - Format: `{"class1": "description1", "class2": "description2"}`
  - If not provided, uses classes from config.toml
- `--provider TEXT`: LLM provider to use (openai, anthropic, ollama, lm_studio)
  - If not provided, uses default from config
- `--output`: Output format: `text` or `json` (default: `text`)
- `--help`: Show help message

**Examples:**

```bash
# Using classes from config
postparse classify multi "Check out this new FastAPI library!"

# Using runtime classes (JSON)
postparse classify multi "Apple announces iPhone 16" \
  --classes '{"recipe": "Cooking instructions", "tech_news": "Technology news", "sports": "Sports updates"}'

# Using classes from file
postparse classify multi "Some text" --classes @my_classes.json

# With specific provider
postparse classify multi "Some text" --provider openai --classes @classes.json

# JSON output
postparse classify multi "Some text" --output json
```

**Output:**
```
╭─ Classification Result ─────────────────────────────────╮
│ Predicted Class: python_package                         │
│ Confidence: 92.00%                                      │
│ Reasoning: The text mentions FastAPI library and APIs   │
│ Available Classes: recipe, python_package, movie_review │
╰─────────────────────────────────────────────────────────╯
```

#### `postparse classify multi-batch`

Classify multiple texts into custom categories.

**Usage:**
```bash
postparse classify multi-batch TEXTS... [OPTIONS]
postparse classify multi-batch @FILE [OPTIONS]
```

**Arguments:**
- `TEXTS...`: Multiple texts to classify (space-separated)
- `@FILE`: File path with one text per line (prefix with @)

**Options:**
- `--classes TEXT`: Class definitions (same as single command)
- `--provider TEXT`: LLM provider to use
- `--output PATH`: Save results to JSON file
- `--help`: Show help message

**Examples:**

```bash
# Multiple texts from command line
postparse classify multi-batch \
  "Boil pasta for 10 minutes" \
  "New Python 3.13 released" \
  "Great movie last night" \
  --classes '{"recipe": "Cooking", "tech_news": "Tech", "movie_review": "Movies"}'

# From file
postparse classify multi-batch @texts.txt \
  --classes @classes.json \
  --output results.json

# With specific provider
postparse classify multi-batch @texts.txt \
  --provider openai \
  --output results.json
```

**Output:**
```
┏━━━━━━━━━━━━━━━━━━━━━━┳━━━━━━━━━━━━━━━━━┳━━━━━━━━━━━━┓
┃ Text                 ┃ Predicted Class ┃ Confidence ┃
┡━━━━━━━━━━━━━━━━━━━━━━╇━━━━━━━━━━━━━━━━━╇━━━━━━━━━━━━┩
│ Boil pasta for...    │ recipe          │ 95.00%     │
│ New Python 3.13...   │ tech_news       │ 89.00%     │
│ Great movie last...  │ movie_review    │ 88.00%     │
└──────────────────────┴─────────────────┴────────────┘

Summary: 3 texts classified
Distribution: recipe (1), tech_news (1), movie_review (1)
```

**Classes File Format:**

Create a JSON file with class definitions:

```json
{
  "recipe": "A text containing cooking instructions, ingredients, or recipe details. Examples: 'Boil pasta', 'Mix flour and eggs'",
  "python_package": "A text about Python packages, libraries, or pip installations. Examples: 'Install FastAPI', 'This library provides async support'",
  "movie_review": "A text reviewing or discussing movies, films, or TV shows. Examples: 'Just watched a thriller', 'The acting was superb'",
  "tech_news": "Technology news, product launches, or software releases. Examples: 'Apple announces iPhone', 'OpenAI releases GPT-5'"
}
```

**Tips:**

1. **Class Descriptions**: Provide detailed descriptions with examples for better accuracy
2. **Number of Classes**: Use 2-10 classes for best results
3. **Provider Selection**: Use OpenAI or Anthropic for best accuracy; Ollama/LM Studio for local/free inference
4. **Batch Processing**: Use batch command for multiple texts to save time
5. **Output Format**: Use `--output` to save results for further processing

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

