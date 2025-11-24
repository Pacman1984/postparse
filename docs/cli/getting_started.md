# Getting Started with PostParse CLI

Quick guide to get up and running with the PostParse command-line interface.

## Installation

### Using UV (Recommended)

```bash
uv pip install postparse
```

### From Source

```bash
git clone https://github.com/sebpachl/postparse.git
cd postparse
uv sync
```

### Verify Installation

```bash
postparse --version
postparse info
```

## Initial Setup

### 1. Configuration

Create your configuration file:

```bash
mkdir -p config
```

Create `config/config.toml`:

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

### 2. Environment Variables

Set your credentials (recommended approach):

**Option A: Create `.env` file (Easiest)**

Create `config/.env`:

```bash
# Telegram
TELEGRAM_API_ID=12345678
TELEGRAM_API_HASH=abc123def456

# Instagram
INSTAGRAM_USERNAME=myuser
INSTAGRAM_PASSWORD=mypass

# LLM APIs (optional)
OPENAI_API_KEY=sk-...
```

The CLI automatically loads from `config/.env` or `.env`.

**Option B: Export variables**

```bash
export TELEGRAM_API_ID=12345678
export TELEGRAM_API_HASH=abc123def456
export INSTAGRAM_USERNAME=myuser
export INSTAGRAM_PASSWORD=mypass
```

**Tip:** Add to `.bashrc` or `.zshrc` to persist across sessions.

### 3. Verify Setup

```bash
postparse config validate --fix
```

## First Extraction

### Telegram Setup

> **Note:** PostParse extracts messages from your **Saved Messages** folder only (not channels or chats).

1. Get API credentials from https://my.telegram.org
2. Set environment variables (see above)
3. Run extraction:

```bash
postparse extract telegram --limit 10
```

On first run, you'll be prompted for:
- Phone number (international format: `+1234567890`)
- Verification code from Telegram
- 2FA password (if enabled)

**What Gets Extracted:**
- Only messages you've saved to "Saved Messages"
- Text, photos, videos, and captions
- Hashtags and metadata

### Instagram Setup

```bash
postparse extract instagram --limit 10
```

Instagram will use your credentials to login and extract saved posts.

## Check for New Content

Before extracting, check what's new (quick preview):

```bash
# Check both platforms (fast: ~3-4 minutes)
postparse check

# Check specific platform
postparse check telegram
postparse check instagram
```

The check command samples 20 newest items to estimate what's new without downloading everything.

## View Your Data

```bash
# Check database stats
postparse stats

# Search posts
postparse search posts

# View detailed stats with hashtags
postparse stats --detailed
```

## Common Commands

```bash
# Get help
postparse --help
postparse extract --help

# System info
postparse info

# Start API server
postparse serve

# Export data
postparse db export data.json

# Validate config
postparse config validate
```

## Troubleshooting

### Config Not Found

```bash
# Create config directory
mkdir -p config

# Check current config
postparse config show
```

### Empty Database

Database is empty after fresh install. Run extraction:

```bash
postparse extract telegram --limit 10
postparse extract instagram --limit 10
```

### Authentication Issues

**Telegram:**
- Delete session: `rm telegram_session.session`
- Re-authenticate: `postparse extract telegram`

**Instagram:**
- Check credentials
- Try logging in via web first
- Check for 2FA settings

### Verbose Mode

Get detailed error information:

```bash
postparse --verbose COMMAND
```

## Next Steps

- 📖 [Command Reference](reference.md) - Complete command documentation
- 🍳 [Cookbook](cookbook.md) - Practical examples and workflows
- ⚙️ [Configuration Guide](../getting_started.md) - Advanced configuration

---

**Quick Links:**
- [Main Documentation](../index.md)
- [API Documentation](../api_reference.md)
- [GitHub Issues](https://github.com/sebpachl/postparse/issues)

