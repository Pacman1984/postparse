# Basic Usage

## CLI Commands

| Command | Purpose |
|---------|---------|
| `postparse stats` | Database statistics |
| `postparse check` | Preview new content (no download) |
| `postparse extract telegram` | Extract from Saved Messages |
| `postparse extract instagram` | Extract saved posts |
| `postparse classify text "..."` | Classify single text |
| `postparse classify db` | Classify database content |
| `postparse search posts --hashtag recipe` | Search by hashtag |
| `postparse serve` | Start API server |

## Extract Workflow

```bash
# Check for new content
postparse check telegram

# Extract (first run prompts for verification)
postparse extract telegram --api-id $TELEGRAM_API_ID --api-hash $TELEGRAM_API_HASH --limit 100

# Classify
postparse classify db --source telegram --limit 100

# Search
postparse search messages --hashtag recipe
```

## Enrich and Classify Pipeline

```bash
postparse extract all
postparse enrich scrape
postparse classify db --classifier multilabel
```

## Get Help

```bash
postparse --help
postparse extract telegram --help
postparse classify db --help
```
