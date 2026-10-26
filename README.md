# PostParse

PostParse collects your **saved Telegram messages** and **saved Instagram posts**
into a local SQLite archive and makes them useful:

- **Incremental collection** from Telegram (Telethon, Saved Messages) and Instagram
  (instaloader, saved feed) — only new items, throttled, resumable.
- **Full-text search** (SQLite FTS5) over captions, transcripts, summaries,
  fetched link texts and tags, with filters for source, tags, authors, kinds,
  labels and dates.
- **Video transcription** with local faster-whisper (CUDA or CPU) or any
  OpenAI-compatible API; no media files are kept.
- **Link enrichment**: article text (trafilatura / readability), PDFs and Office
  documents (markitdown), YouTube metadata and transcripts, X posts (fxtwitter).
- **LLM summaries and classification** into your own taxonomies (pydantic-ai;
  llama.cpp, LM Studio, Ollama, vLLM, OpenAI, Anthropic), versioned per label set.
- A **CLI** (`postparse`) and a **FastAPI REST API** on the same services, with
  background jobs and WebSocket progress.

Documentation: [docs/](docs/index.md) · Changes: [CHANGELOG.md](CHANGELOG.md)

## Requirements

- Python **3.12+** and [uv](https://docs.astral.sh/uv/)
- SQLite **3.45+** (bundled with current Python builds)
- Telegram API credentials (my.telegram.org) and/or an Instagram account
- For classification and summaries: an LLM endpoint (for example llama.cpp)
- For local transcription: optional `asr` extra; an NVIDIA GPU is optional (CPU works)

## Installation

```bash
git clone https://github.com/Pacman1984/postparse.git
cd postparse
uv sync                                # core
uv sync --extra asr --extra youtube    # optional extras, combine as needed
```

| Extra | Adds |
|---|---|
| `asr` | faster-whisper plus NVIDIA cuBLAS / cuDNN 9 wheels (local transcription, CUDA without a system toolkit) |
| `youtube` | yt-dlp (pinned) for YouTube descriptions, chapters, tags, duration |
| `migrate` | ftfy, repairs mojibake when migrating schema v1 data |
| `notebooks` | data-science stack for the exploratory notebooks |

Then create your configuration:

```bash
cp config/config.example.toml config/config.toml
cp config/.env.example config/.env     # fill in TELEGRAM_* / INSTAGRAM_* / API keys
uv run postparse config validate --fix
```

## Quick start: the refresh pipeline

```bash
uv run postparse extract all                     # new Telegram + Instagram items
uv run postparse transcribe run --limit 50       # pending videos (throttled)
uv run postparse enrich run                      # linked pages, documents, videos, X posts
uv run postparse summarize run                   # items with new transcripts
uv run postparse classify run --taxonomy topics  # LLM labels for pending items
uv run postparse search items pasta --label topics:recipe
```

The first `extract` asks for the Telegram login code (and 2FA password) and, if
needed, an Instagram 2FA code; later runs reuse the saved sessions.

Every step only processes what is pending and can be re-run at any time.
`classify run` uses the **default scope**: items collected after the taxonomy was
created plus items that were never classified. Old, already classified posts
are never re-classified automatically; use `--backfill` (everything not yet
classified for the current label set) or `--reprocess` (everything matching the
filters) explicitly. See [Taxonomies](docs/taxonomies.md) and the
[operations runbook](docs/operations.md).

## Upgrading from 0.1 (schema v1)

0.2 uses a new database (`data/postparse.db`, schema v2). Back up your v1 file
first, then migrate into a new file (the source is opened read-only):

```bash
mkdir -p backup && cp data/social_media.db backup/social_media.db
uv sync --extra migrate
uv run postparse db migrate-v1 --source data/social_media.db --target data/postparse.db \
    --report data/migrate-v1-report.json
uv run postparse db check
```

Naive v1 Instagram timestamps are interpreted as `Europe/Berlin`
(`--instagram-tz`); `extract instagram --refresh-dates` verifies them later.
Details: [Database](docs/database.md#upgrading-from-schema-v1),
[CHANGELOG](CHANGELOG.md).

## Configuration

- `config/config.toml` — settings; every key is documented in
  [`config/config.example.toml`](config/config.example.toml).
- `config/.env` — credentials (names in [`config/.env.example`](config/.env.example)),
  loaded by every CLI command; `POSTPARSE_NO_DOTENV=1` disables loading.
- `POSTPARSE_DATA_DIR`, `POSTPARSE_DB_PATH`, `POSTPARSE_SESSIONS_DIR`,
  `POSTPARSE_DOWNLOADS_DIR`, `POSTPARSE_TMP_DIR` override paths;
  `POSTPARSE_CONFIG` selects the config file of the API app.

`postparse config show` prints the effective configuration (secrets masked),
`postparse config env` which variables are set. More: [Configuration](docs/configuration.md).

## CLI overview

| Command | Purpose |
|---|---|
| `extract telegram \| instagram \| all` | Collect new saved items (`--stop-after-known`, `--force`, `--refresh-dates`, `--transcribe`) |
| `transcribe run \| status` | Work through the video transcription queue |
| `enrich run \| status` | Fetch linked URLs and store their text |
| `summarize run` | Summarize items with new transcripts |
| `classify run \| text \| taxonomies` | Classify pending items, free text, list taxonomies (`classify db` is a deprecated alias) |
| `search items \| posts \| messages` | Full-text search with filters, JSON output, cursor pagination |
| `stats` (= `db stats`), `info` | Counts, queues, coverage; installation and paths |
| `db migrate \| check \| reindex \| export \| migrate-v1` | Database maintenance, export to JSON/CSV, v1 import |
| `check all \| db \| llm \| telegram \| instagram \| transcription` | Health checks |
| `config show \| validate \| env` | Configuration |
| `serve` | Start the REST API |

Full reference generated from `--help`: [CLI reference](docs/cli-reference.md).

### Exit codes

| Code | Meaning |
|---|---|
| `0` | success |
| `1` | error |
| `2` | login required (Telegram/Instagram session invalid, 2FA needed non-interactively) |
| `3` | rate limited, or suspected Instagram soft block |
| `130` | interrupted (Ctrl-C) |

## API overview

```bash
uv run postparse serve            # http://localhost:8000/docs
```

- `GET /api/v1/items` (search with every CLI filter), `/items/{id}`, `/stats`, `/taxonomies`
- Jobs: `POST /api/v1/{telegram,instagram}/extract`, `/transcription/run`,
  `/summaries/run`, `/enrichment/run`, `/classify/run`; status via
  `GET /api/v1/jobs/{id}`, live progress via `WS /api/v1/jobs/{id}/ws`
- `POST /api/v1/classify/{taxonomy}` (optionally `persist=true`), ad-hoc classifiers
- `GET /health`, `/health/ready`; optional JWT auth, rate limiting, CORS, Redis cache

`postparse serve` loads `config/.env`; plain `uvicorn postparse.api.main:create_app
--factory` does not. Run one worker (jobs live in process memory). Details:
[API reference](docs/api-reference.md).

## Development

```bash
uv sync --group dev --extra migrate --extra youtube
uv run pytest -q                       # isolated: no network, accounts or real data
uv run pytest --run-live               # include tests against real LLM servers
uv run ruff check && uv run ruff format --check
uv run mypy src
uv run --group docs mkdocs build --strict
```

CI (GitHub Actions) runs ruff, mypy and pytest on Ubuntu and Windows with
Python 3.12 and 3.13. See [Testing](docs/testing.md).

## License

MIT, see [LICENSE](LICENSE).
