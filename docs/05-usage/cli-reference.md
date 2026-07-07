# CLI Reference

## Global Options

| Option | Description |
|--------|-------------|
| `--config PATH` | Custom config file |
| `--verbose` | Verbose output |
| `--quiet` | Suppress non-essential output |
| `--version` | Show version |
| `--help` | Help message |

## Core Commands

### postparse stats

Database statistics (alias for `postparse db stats`).

- `--detailed` — Include hashtag distribution

### postparse info

Installation and version info.

### postparse check

Check for new content without downloading.

- `telegram` — Telegram only
- `instagram` — Instagram only
- `all` — Both (default)

### postparse extract

Extract from platforms.

- `all` — Both (default)
- `telegram` — Saved Messages
- `instagram` — Saved posts

Options: `--limit`, `--force`, `--api-id`, `--api-hash`, `--phone`, `--username`, `--password`

### postparse classify

**text** — Ad-hoc (does not save): `postparse classify text "Mix flour and water"`

**db** — Classify database content and save:
- `--source` telegram | instagram | all
- `--classifier` recipe | multiclass | multilabel
- `--classes` JSON or `@file.json`
- `--provider` Provider name
- `--limit`, `--force`, `--replace`

### postparse search

- `posts` — Instagram: `--hashtag`, `--from`, `--to`, `--type`
- `messages` — Telegram: same filters

### postparse enrich

- `urls` — Extract URLs to content_expanded
- `scrape` — Fetch URL content, save to content_expanded. Options: `--source`, `--limit`, `--force`, `--timeout`

### postparse serve

Start API server.

- `--host`, `--port`, `--reload`, `--workers`, `--log-level`

### postparse db

- `stats` — Database statistics
- `export` — Export to JSON/CSV. Options: `--format`, `--source`, `--limit`

### postparse config

- `show` — Display config (`--section` for specific)
- `validate` — Validate config file
- `env` — Show loaded env vars

## Help

```bash
postparse --help
postparse extract telegram --help
postparse classify db --help
```
