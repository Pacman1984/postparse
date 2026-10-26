# Changelog

All notable changes to PostParse are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/); versions follow
[Semantic Versioning](https://semver.org/) (pre-1.0: minor versions may break).

## [Unreleased]

### Fixed

- **Instagram session check**: the saved session is no longer verified with
  instaloader's `test_login()` (legacy GraphQL `query_hash` d6f4427…, which
  Instagram answers with 401 "Please wait a few minutes", and which reported
  every error as "not logged in"). The check now reads the `sessionid` /
  `ds_user_id` cookies and asks `api/v1/users/<id>/info/` once (single
  connection attempt). A throttled or failed check raises the new
  `InstagramSessionCheckFailed` (a subclass of `InstagramRateLimited`, exit
  code 3) and **never falls back to a password login**; the session file is
  left untouched. The password login is only used when the session is
  positively logged out.
- **Instagram saved feed**: collected through the private API
  (`api/v1/feed/saved/posts/`, paginated with `max_id`) instead of
  `Profile.own_profile().get_saved_posts()`, which use legacy GraphQL
  `query_hash` queries. Owners, comment counts and carousel video children
  (with durations) are read from the private API media structs.
- `AbortDownloadException` (checkpoint, login redirect) during a run is mapped
  to `InstagramAuthRequired`.

## [0.2.0] - 2026-10-26

A rewrite of the storage, LLM, collection and API layers. The CLI command names
are largely kept; the Python API and the database are new.

### Breaking changes

- **Python 3.12+** is required (was 3.10+).
- **src layout**: the package lives in `src/postparse` and is imported as
  `postparse` (the old `backend.postparse` paths are gone).
- **New database (schema v2)** at `data/postparse.db` (`[database] db_path`,
  `POSTPARSE_DB_PATH`) with SQL migrations, STRICT tables, UTC timestamps and an
  FTS5 index. The v1 layer (`SocialMediaDatabase`, `data/social_media.db`) was
  removed; `[database] default_db_path` / `path` are ignored with a warning.
  Convert existing data with `postparse db migrate-v1` (see below).
- **LLM stack**: LangChain and LiteLLM were replaced by pydantic-ai. The
  recipe / multi-class / multi-label classifiers were replaced by one generic
  taxonomy workflow configured with `[[classification.taxonomies]]`
  (`[[classification.classes]]` still works as the `topics` taxonomy).
- **Old parsers removed** (`InstaloaderParser`, `save_telegram_messages`, the
  `services/parsers` and `services/analysis` packages, the old API extraction
  service, `content_expanded` handling). Use the collectors via
  `postparse extract ...` or `ExtractionService`.
- **CLI changes**: `classify db` is a deprecated alias of
  `classify run --taxonomy topics`; `enrich scrape` is a deprecated alias of
  `enrich run`; `enrich urls` is a deprecated no-op (links are extracted when
  items are stored). `search posts` / `search messages` are aliases of
  `search items --source ...`. `check` was reduced to
  `all | db | llm | telegram | instagram | transcription`.
- **Session files** default to `<data_dir>/sessions/` (`telegram.session`,
  `instagram_<username>`); the old locations are still used as fallbacks.
- **API**: services are created in the FastAPI lifespan (`create_app()`);
  `postparse.api.main:app` is created lazily from `POSTPARSE_CONFIG`. The API no
  longer reads `.env` files itself (`postparse serve` still does). Response
  schemas of existing endpoints are kept; old paths remain as aliases.

### Migration steps (0.1 → 0.2)

1. Back up `data/social_media.db`, `data/downloads/` and your session files.
2. `uv sync` (add `--extra migrate` for ftfy text repair, `--extra asr` for
   local transcription, `--extra youtube` for yt-dlp metadata).
3. Create `config/config.toml` from `config/config.example.toml`; move the
   classification classes into `[[classification.taxonomies]]`, configure
   `[[llm.providers]]`, remove the v1 database keys.
4. `postparse db migrate-v1 --source data/social_media.db --target data/postparse.db --report data/migrate-v1-report.json`
   (naive Instagram times are interpreted as `Europe/Berlin`; change with
   `--instagram-tz`), then `postparse db check`.
5. Work off the backlog: `postparse enrich run`, daily
   `postparse transcribe run --limit 50`, `postparse summarize run`, and
   `postparse classify run -t topics --backfill` if your labels changed.
6. Optionally verify migrated Instagram dates with
   `postparse extract instagram --refresh-dates --refresh-limit 200`.

### Added

- Schema v2 database: repositories, `QueryService` (keyset pagination, filters,
  FTS snippets, item detail, JSON/CSV export), view `v_current_classification`,
  `db migrate | check | reindex | migrate-v1 | export | stats`.
- Generic taxonomy classification on pydantic-ai: single/multi-label taxonomies
  with label descriptions, versioning by label-set hash, pending scopes
  `default` / `backfill` / `reprocess`, input composed from caption,
  transcripts, summary and link texts; `classify run | text | taxonomies`.
- LLM providers: OpenAI-compatible servers (llama.cpp, LM Studio, Ollama, vLLM)
  and Anthropic; native JSON-schema output for self-hosted endpoints, served
  model discovery, per-provider concurrency; `check llm`.
- Incremental collectors: Telegram (Telethon, `min_id`, resumable, FloodWait
  handling) and Instagram (instaloader, stop after N known posts,
  `--stop-after-known`, batched commits, `--refresh-dates` with
  `instagram_posts.date_status`); `extract telegram | instagram | all` with exit
  codes 2 (login required) and 3 (rate limited).
- Video transcription: local faster-whisper (`asr` extra, CUDA via NVIDIA
  wheels with CPU fallback) or any OpenAI-compatible transcription API; throttled
  Instagram re-fetches of expired video URLs, retry backoff, soft-block circuit
  breaker (`max_consecutive_refetch_failures`), no media files kept;
  `transcribe run | status`, `extract instagram --transcribe`.
- LLM summaries of transcribed items: `summarize run`.
- Per-link enrichment: trafilatura/readability articles, markitdown documents,
  YouTube oEmbed + yt-dlp (`youtube` extra) + transcripts, X posts via
  fxtwitter, Instagram links skipped; per-domain throttle, retry backoff;
  `enrich run | status`.
- CLI: `search items` (full text, tags, authors, kinds, labels, dates,
  transcripts, `--json`, cursors), `stats` with queues and pending counts,
  `info`, `config show | validate | env`.
- REST API on the shared services: `JobRunner` with job kinds
  `telegram_extract`, `instagram_extract`, `transcribe`, `summarize`, `enrich`,
  `classify`; `/api/v1/items`, `/stats`, `/taxonomies`,
  `/transcription/run|status`, `/summaries/run`, `/enrichment/run|status`,
  `/classify/run`, `/classify/{taxonomy}[/batch]` with `persist`, unified
  `/jobs` + `/jobs/{id}/ws`, `/health/ready` with database, LLM and
  transcription checks; namespaced cache keys with invalidation after jobs.
- Settings via `POSTPARSE_DATA_DIR`, `POSTPARSE_DB_PATH`,
  `POSTPARSE_SESSIONS_DIR`, `POSTPARSE_DOWNLOADS_DIR`, `POSTPARSE_TMP_DIR`,
  `POSTPARSE_CONFIG`; `POSTPARSE_NO_DOTENV` disables `.env` loading.
- Extras `asr`, `youtube`, `migrate`, `notebooks`; dependency groups `dev` and
  `docs`.
- Tooling: ruff (lint + format) and mypy (strict for the library core), GitHub
  Actions CI on Ubuntu and Windows with Python 3.12 / 3.13, isolated test suite
  (no network, no real config, `.env` or data), `--run-live` for live tests.
- Documentation rewritten for the v2 architecture (`docs/`, MkDocs), commented
  `config/config.example.toml` and `config/.env.example`.

### Removed dependencies

- **litellm**, **langchain-core**, **langchain-litellm**, **langchain-community**:
  replaced by pydantic-ai-slim and the openai / anthropic SDKs. Besides the large
  transitive dependency tree, litellm was a supply-chain risk: compromised
  releases were published to PyPI in 2026, which is why 0.2 development first
  pinned it to a known-good version and then removed it entirely.
- **python-jose** → PyJWT (same HS256 validation); **toml** → stdlib `tomllib`.
- **nest-asyncio**, **tenacity**, **email-validator**: no longer used.
- black, isort, pylint → ruff. The data-science stack (pandas, scikit-learn,
  xgboost, ...) moved to the `notebooks` extra.

### Fixed

- Instagram extraction jobs in the API always failed; a failed Telegram job
  crashed with a `None` dereference.
- API list endpoints ignored `offset`, owner and channel filters and returned no
  hashtags; search filters were expected as GET request bodies.
- Blocking database and network work ran inside async API handlers.
- The API response cache was never invalidated.
- Batch classification dropped per-item errors; API classification never
  persisted results.
- `postparse serve --config` did not reach the app; an uppercase log level broke
  uvicorn.
- Valid Instagram reels were marked `skipped` permanently when Instagram
  soft-blocked the session (now retried with backoff, plus a circuit breaker).
- Piped or redirected CLI output crashed with `UnicodeEncodeError` on Windows.
- Rich tracebacks no longer show local variables (could contain secrets).
- CLI help and warnings no longer swallow TOML table names such as
  `[[llm.providers]]` (rich markup).

## [0.1.0]

Initial version: Telegram and Instagram parsers, `SocialMediaDatabase`
(schema v1), LangChain/LiteLLM classifiers, CLI and FastAPI server.
