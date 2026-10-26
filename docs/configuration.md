# Configuration

PostParse reads a TOML file for settings and the environment (optionally from a
`.env` file) for credentials. The fully commented reference is
[`config/config.example.toml`](https://github.com/Pacman1984/postparse/blob/master/config/config.example.toml);
the variable names are in
[`config/.env.example`](https://github.com/Pacman1984/postparse/blob/master/config/.env.example).

```bash
cp config/config.example.toml config/config.toml
cp config/.env.example config/.env       # then fill in your values
postparse config validate                # add --fix to create missing data directories
postparse config show                    # effective values, secrets masked
postparse config env                     # which variables are set (never their values)
```

Both `config/config.toml` and `config/.env` are git-ignored; the `*.example`
files are tracked.

## Config file discovery

The first match wins:

1. the root option `postparse --config PATH ...` (must exist);
2. `./config/config.toml`;
3. `./config.toml`;
4. `<project root>/config/config.toml` (source checkout).

The API server (`postparse.api.main`) uses `POSTPARSE_CONFIG` when set (and the
same search otherwise). `postparse serve` sets `POSTPARSE_CONFIG` to the file it
loaded, so the server uses exactly the same configuration as the CLI.
`POSTPARSE_CONFIG` has no effect on other CLI commands.

Without any config file, the CLI and API run with built-in defaults (paths
below `./data`, no LLM providers, no taxonomies).

## Sections

| Section | Read by | Notes |
|---|---|---|
| `[paths]` | `Settings` | `data_dir` (default `data`), `sessions_dir`, `downloads_dir`, `tmp_dir` (defaults below `data_dir`) |
| `[database]` | `Settings` | `db_path` (default `<data_dir>/postparse.db`). The v1 keys `default_db_path` / `path` are ignored with a warning. |
| `[llm]`, `[[llm.providers]]` | classification, summaries, `check llm`, `/health/ready` | `default_provider` (required) plus one table per provider: `name`, `model`, `api_base`, `api_key`, `timeout`, `max_retries`, `temperature`, `max_tokens`, `custom_params`, `api_type`, `output_mode`, `max_concurrency`, `discover_model` |
| `[classification]`, `[[classification.taxonomies]]` | `ClassificationService` | `max_input_chars`; taxonomies, see [Taxonomies](taxonomies.md) |
| `[transcription]`, `.local`, `.api` | `TranscriptionService` | see [Transcription](transcription.md) |
| `[summarization]` | `SummarizationService` | `provider`, `max_input_chars`, `output_retries` |
| `[enrichment]` | `EnrichmentService` | see [Enrichment](enrichment.md) |
| `[telegram]` | Telegram collector | batch size, FloodWait threshold, media download limits and pauses, Telethon retry settings |
| `[instagram]` | Instagram collector | pauses between posts (`default_min_delay` / `default_max_delay`) and date refreshes, instaloader timeout / attempts, `user_agent`, `feed_api` (`"web"`: saved feed like the web app on `www.instagram.com`, default; `"iphone"`: private API on `i.instagram.com`) |
| `[api]` and `[api.auth]`, `[api.cors]`, `[api.rate_limiting]`, `[api.cache]`, `[api.jobs]` | `serve`, FastAPI app | see [API reference](api-reference.md) |

### LLM provider example (llama.cpp)

```toml
[llm]
default_provider = "llama_cpp"

[[llm.providers]]
name = "llama_cpp"
model = "local"                      # replaced by the served model (discovery)
api_base = "http://<host>:1235/v1"
timeout = 120
temperature = 0.0
max_concurrency = 1
discover_model = true
```

API keys are read from the environment when `api_key` is not set:
`OPENAI_API_KEY` for providers named `openai` or `lm_studio`,
`ANTHROPIC_API_KEY` for `anthropic`. Self-hosted endpoints work without a key.
`postparse check llm` lists the served models and sends a chat ping.

`enable_fallback` and `cache_responses` in `[llm]` are accepted for
compatibility but currently have no effect: every call uses the selected
provider only.

## Environment variables

| Variable | Purpose |
|---|---|
| `TELEGRAM_API_ID`, `TELEGRAM_API_HASH`, `TELEGRAM_PHONE` | Telegram API credentials (phone optional, used for the first login) |
| `INSTAGRAM_USERNAME`, `INSTAGRAM_PASSWORD` | Instagram login (password optional while the session file is valid) |
| `OPENAI_API_KEY`, `ANTHROPIC_API_KEY` | LLM providers; the transcription API backend reads the variable named by `transcription.api.api_key_env` (default `OPENAI_API_KEY`) |
| `JWT_SECRET_KEY` | API authentication secret (fallback when `api.auth.secret_key` is not set) |
| `POSTPARSE_DATA_DIR`, `POSTPARSE_DB_PATH`, `POSTPARSE_SESSIONS_DIR`, `POSTPARSE_DOWNLOADS_DIR`, `POSTPARSE_TMP_DIR` | override the corresponding `[paths]` / `[database]` values |
| `POSTPARSE_CONFIG` | config file of the API app (set by `postparse serve`) |
| `POSTPARSE_NO_DOTENV` | any non-empty value disables `.env` loading |
| `POSTPARSE_API_HOST`, `POSTPARSE_API_PORT` | only for `python -m postparse.api.main` (default `127.0.0.1:8000`) |

Precedence for paths: environment variable > config file > built-in default.
Relative paths resolve against the current working directory.

## `.env` loading

When the CLI starts (every command, including `postparse serve`), it loads the
first file found of `./config/.env`, `./.env`, `<project root>/config/.env`,
`<project root>/.env`. Variables that are already set in the environment win.
`POSTPARSE_NO_DOTENV=1` disables this (the test suite and CI always set it).

The API module itself never reads `.env` files. Started via `postparse serve`,
the server inherits the environment the CLI prepared; started directly with
`uvicorn postparse.api.main:create_app --factory`, export the variables first.

## Default file locations

| Path | Content |
|---|---|
| `data/postparse.db` | schema v2 database |
| `data/sessions/telegram.session` | Telethon session (fallback: legacy `data/cache/telegram_session.session`) |
| `data/sessions/instagram_<username>` | instaloader session (fallback: `./instagram_session`) |
| `data/downloads/` | downloaded Telegram media (`media.local_path` is relative to it) |
| `data/tmp/transcribe/` | scratch directories of `transcribe run` (deleted after each media) |

Session files are credentials: keep them private (they are git-ignored).
