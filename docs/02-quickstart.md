# Quickstart

## Prerequisites

- Python 3.10+
- [UV](https://docs.astral.sh/uv/) (recommended) or pip
- Telegram API credentials (for Telegram extraction)
- Instagram account (for Instagram extraction)

## Install

```bash
# Using UV (recommended)
uv pip install postparse

# From source
git clone https://github.com/sebpachl/postparse.git
cd postparse
uv sync
```

## Minimal Example

```bash
# Show help
postparse --help

# Check database and for new content
postparse stats
postparse check

# Extract Telegram messages (from Saved Messages)
postparse extract telegram --api-id 12345 --api-hash abc123

# Classify text
postparse classify text "Mix flour and water to make dough"

# Start the API server
postparse serve --port 8080
```

## Expected Output

```
postparse stats
```
Shows database summary: total posts, messages, date ranges, content breakdown.

```
postparse extract telegram --limit 10
```
Extracts 10 most recent saved messages. First run prompts for verification code.

## Next Steps

1. [Configure](07-configuration.md) `config/config.toml` and credentials
2. [Extract](05-usage/basic.md) from Telegram and Instagram
3. [Classify](08-examples/recipes.md) content with `postparse classify db`
