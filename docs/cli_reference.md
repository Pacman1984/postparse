# PostParse CLI Reference

Complete command-line interface reference for PostParse.

> **📖 For the most comprehensive CLI documentation with detailed examples, output samples, and troubleshooting, see [CLI Reference (Detailed)](cli/reference.md)**

## Quick Navigation

- **[Getting Started](getting_started.md)** - Installation and first steps
- **[CLI Reference (Detailed)](cli/reference.md)** - Complete command reference with examples
- **[Cookbook](cookbook.md)** - Practical examples and workflows

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

**Examples:**
```bash
postparse check                    # Check all platforms
postparse check telegram           # Check Telegram only
postparse check instagram          # Check Instagram only
```

## Data Operations

### `postparse extract`

Extract data from social media platforms.

**Subcommands:**
- `all` - Extract from both platforms (default)
- `telegram` - Extract from Telegram Saved Messages
- `instagram` - Extract Instagram saved posts

**Examples:**
```bash
postparse extract                    # Extract from all platforms
postparse extract telegram --api-id 12345 --api-hash abc123
postparse extract instagram --username myuser --password mypass
```

### `postparse classify`

Classify content using LLM classifiers.

**Subcommands:**
- `text` - Classify free-form text (ad-hoc, doesn't save to database)
- `db` - Classify database content and save results

**Examples:**
```bash
# Ad-hoc text classification
postparse classify text "Mix flour and water to make dough"

# Database classification (saves results)
postparse classify db --limit 100
postparse classify db --source instagram --limit 100
postparse classify db --classifier multiclass \
  --classes '{"recipe": "Cooking", "tech": "Technology"}'
```

### `postparse search`

Search stored posts and messages.

**Subcommands:**
- `posts` - Search Instagram posts
- `messages` - Search Telegram messages

**Examples:**
```bash
postparse search posts --hashtag recipe
postparse search messages --hashtag recipe
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

**Examples:**
```bash
postparse config show
postparse config show --section llm
postparse config validate
postparse config env
```

## Getting Help

```bash
postparse --help                    # All commands
postparse COMMAND --help            # Specific command help
postparse COMMAND SUBCOMMAND --help # Subcommand help
postparse info                      # System information
```

---

**See Also:**
- [CLI Reference (Detailed)](cli/reference.md) - Complete reference with examples and output samples
- [Getting Started](getting_started.md) - Installation and first steps
- [Cookbook](cookbook.md) - Practical examples and workflows
- [API Reference](api_reference.md) - REST API documentation
