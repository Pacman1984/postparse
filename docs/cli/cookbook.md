# CLI Cookbook

Practical recipes for common PostParse CLI workflows.

## Quick Recipes

### Check Before Extracting

```bash
# Quick preview of new content (3-4 minutes)
postparse check

# Check specific platform
postparse check telegram
postparse check instagram
```

### Extract and View Data

```bash
# Extract limited data for testing
postparse extract telegram --limit 50
postparse stats

# Extract all saved content
# Note: Telegram extracts from "Saved Messages" folder only
postparse extract telegram
postparse extract instagram
```

### Search and Filter

```bash
# Find recipes
postparse search posts --hashtag recipe
postparse search messages --hashtag recipe

# Filter by date
postparse search posts --from 2024-01-01 --to 2024-12-31

# Filter by content type
postparse search posts --type video
postparse search messages --type photo

# Multiple filters
postparse search posts --hashtag recipe --hashtag cooking --type video
```

### Classification

```bash
# Classify single text
postparse classify single "Mix flour and water to make dough"

# From stdin
echo "Boil pasta for 10 minutes" | postparse classify single -

# Batch classification
postparse classify batch --source posts --limit 100
postparse classify batch --filter-hashtag recipe --detailed

# With specific LLM provider
postparse classify batch --provider openai --detailed
```

### Data Export

```bash
# Export all data to JSON
postparse db export data.json

# Export only posts
postparse db export posts.json --source posts

# Export to CSV
postparse db export data.csv --format csv

# Limited export
postparse db export recent.json --limit 1000
```

## Workflows

### Daily Data Sync

```bash
#!/bin/bash
# sync.sh - Daily extraction script with check

# Set credentials (or use config/.env)
export TELEGRAM_API_ID=12345678
export TELEGRAM_API_HASH=abc123def456

# Check for new content first
echo "Checking for new content..."
postparse check

# Extract new data
echo "Extracting Telegram messages (from Saved Messages)..."
postparse extract telegram --limit 100

echo "Extracting Instagram posts..."
postparse extract instagram --limit 50

# Show stats
postparse stats

# Export daily backup
postparse db export "backup_$(date +%Y%m%d).json"
```

### Recipe Collection Pipeline

```bash
# 1. Extract from both platforms
postparse extract telegram --limit 500
postparse extract instagram --limit 200

# 2. Find all recipe-related content
postparse search posts --hashtag recipe --hashtag cooking --output json > recipes_posts.json
postparse search messages --hashtag recipe --output json > recipes_messages.json

# 3. Classify with LLM
postparse classify batch --filter-hashtag recipe --detailed

# 4. Export verified recipes
postparse db export recipes_verified.json --limit 1000
```

### Development Workflow

```bash
# Start API server in development mode
postparse serve --reload --log-level debug

# In another terminal, test with small dataset
postparse extract telegram --limit 10
postparse classify batch --source messages --limit 10

# Check results
postparse stats --detailed
```

### Batch Processing

```bash
# Process large dataset efficiently
postparse extract telegram --limit 5000
postparse extract instagram --limit 1000

# Classify in batches
postparse classify batch --source posts --limit 500
postparse classify batch --source messages --limit 500

# Export results
postparse db export classified_$(date +%Y%m%d).json
```

## Advanced Usage

### Custom Configuration

```bash
# Use different config for different environments
postparse --config config/production.toml stats
postparse --config config/testing.toml extract telegram --limit 10
```

### Scripting

```bash
# JSON output for scripting
posts=$(postparse search posts --hashtag recipe --output json)
echo $posts | jq '.[] | .caption' | head -10

# Quiet mode for cron jobs
postparse --quiet db export daily_backup.json

# Verbose mode for debugging
postparse --verbose extract instagram
```

### Environment-Specific

```bash
# Development
export POSTPARSE_ENV=development
postparse serve --reload --log-level debug

# Production
export POSTPARSE_ENV=production
postparse serve --workers 4 --log-level warning
```

## Automation Examples

### Cron Job - Daily Backup

```bash
# Add to crontab: crontab -e
0 2 * * * cd /path/to/postparse && postparse --quiet db export backup.json
```

### Systemd Service - API Server

```ini
# /etc/systemd/system/postparse.service
[Unit]
Description=PostParse API Server
After=network.target

[Service]
Type=simple
User=postparse
WorkingDirectory=/opt/postparse
Environment="TELEGRAM_API_ID=12345678"
Environment="TELEGRAM_API_HASH=abc123def456"
ExecStart=/usr/local/bin/postparse serve --workers 4
Restart=on-failure

[Install]
WantedBy=multi-user.target
```

### GitHub Actions - Weekly Extract

```yaml
# .github/workflows/extract.yml
name: Weekly Extraction
on:
  schedule:
    - cron: '0 0 * * 0'  # Every Sunday

jobs:
  extract:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v2
      - name: Setup Python
        uses: actions/setup-python@v2
      - name: Install PostParse
        run: pip install postparse
      - name: Extract Data
        env:
          TELEGRAM_API_ID: ${{ secrets.TELEGRAM_API_ID }}
          TELEGRAM_API_HASH: ${{ secrets.TELEGRAM_API_HASH }}
        run: |
          postparse extract telegram --limit 1000
          postparse stats
```

## Tips & Tricks

### Progress Monitoring

```bash
# Watch progress in real-time
postparse extract telegram --limit 1000
# Shows: spinner, progress bar, percentage, time remaining
```

### Credential Management

```bash
# Store in config/.env file (automatically loaded by CLI)
cat > config/.env << EOF
TELEGRAM_API_ID=12345678
TELEGRAM_API_HASH=abc123def456
INSTAGRAM_USERNAME=myuser
INSTAGRAM_PASSWORD=mypass
EOF

# CLI automatically loads config/.env or .env
postparse check
postparse extract telegram
```

### Quick Stats

```bash
# Quick overview
postparse stats

# Detailed with hashtags
postparse stats --detailed

# System info
postparse info
```

### Error Debugging

```bash
# Enable verbose output
postparse --verbose extract instagram

# Check configuration
postparse config validate --fix

# View current config
postparse config show
```

## Common Patterns

### Test Before Production

```bash
# Test with small dataset
postparse extract telegram --limit 10
postparse stats
postparse search posts

# If good, run full extraction
postparse extract telegram
```

### Incremental Extraction

```bash
# Extract only new data (skips existing)
postparse extract telegram --limit 100
# Run daily - only new messages are added
```

### Cleanup and Maintenance

```bash
# View current data
postparse stats --detailed

# Export before cleanup
postparse db export backup_before_cleanup.json

# Remove database and start fresh (if needed)
rm data/social_media.db
postparse extract telegram --limit 10
```

---

**See Also:**
- [Getting Started](getting_started.md)
- [Command Reference](reference.md)
- [Main Documentation](../index.md)

