# Changelog

All notable changes to PostParse are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/); versions follow
[Semantic Versioning](https://semver.org/) (pre-1.0: minor versions may break).

## [Unreleased]

### Added

- **`postparse check instagram --import-session`**: imports the session of
  the user's logged-in browser without a password. The `sessionid` cookie is
  read from a hidden terminal prompt (`csrftoken` optional, generated when
  empty; a `:`-decoded copy is normalized to `%3A`), verified with exactly one
  request (with `feed_api = "web"` the first saved-feed page, see below) and
  saved only when Instagram confirms the session (`InstagramCollector.import_session`). Needs an
  interactive terminal; cannot be combined with `--login`. The value is never
  shown or logged. Messages that tell how to log in now recommend it first and
  `--login` as the alternative. See docs/operations.md.

### Changed

- **Session check over the web API, with the saved feed's first page**: with
  `instagram.feed_api = "web"` (the default) the session check requests the
  first page of the saved feed (`https://www.instagram.com/api/v1/feed/saved/posts/`),
  exactly as the feed walk does and as the Instagram web app does when the
  saved page is opened (same web client and headers, saved page as
  `Referer`, single attempt), instead of `i.instagram.com` with instaloader's
  iPad headers: one client identity per run, and a browser session is never
  sent with iPad headers to `i.instagram.com`. An intermediate version asked
  `www.instagram.com/api/v1/users/<id>/info/`, which the web app does not
  normally call; Instagram answered a fresh `--import-session` there with 429.
  The checked page is reused as the walk's first page, so `extract instagram
  --limit 1 --stop-after-known 1` with a valid session makes exactly one
  request (an import makes one as well). A 200 answer with `"status": "fail"`
  to that page raises `InstagramFeedUnavailable` (not "logged out"); nothing is
  saved. The feed does not name the viewer, so in web mode the account is the
  one the `sessionid` belongs to; `feed_api = "iphone"` keeps the user-info
  check with the username comparison.

- **No automatic Instagram password login**: `extract instagram` (also with
  `--transcribe`), `transcribe run` re-fetches and all API jobs never log in
  with `INSTAGRAM_PASSWORD`. Without a usable session (no session file,
  unreadable file, session logged out) they raise `InstagramAuthRequired`
  (exit code 2, `error_code: auth_required`) that names the reason and says to
  run `postparse check instagram --login` in a terminal; the session file is
  not touched. `InstagramCollector` has a new `allow_password_login` argument
  (default `False`) that only `check instagram --login` sets; it prints a
  warning before the password login. A scripted password login after a
  session check had made Instagram flag the account (confirmation request /
  login redirect on the first feed page).

### Fixed

- **`check instagram --login` saved an unusable session**: instaloader reports
  a password login as successful as soon as Instagram answers
  `authenticated: true`, even when no `sessionid` cookie came back, and keeps
  its empty placeholder cookies in the jar (instaloader issue #2487). The
  placeholders are now removed, a login without `sessionid` / `ds_user_id`
  stops with `InstagramAuthRequired` ("Instagram accepted the password but
  returned no session cookie ...; nothing was saved") and a new session is
  verified with one session check before it is saved (also after a 2FA code).
  Nothing is saved on any failure; the existing session file stays untouched.
  A throttled check of a new session says "did not confirm the session after
  the password login" (still `InstagramSessionCheckFailed`, exit code 3).
- **Cookie values in messages**: `"sessionid": "..."` (JSON) and bare
  `sessionid` values are redacted as well.
- **Instagram's reason in messages**: logged-out sessions, confirmations,
  feed refusals and rate limits quote Instagram's sanitized short reason
  (`message "..."`, e.g. `checkpoint_required`, or a login redirect as
  `scheme://host/path`); query strings, cookies, tokens and response bodies
  are never included (at most 200 characters). A failed session check no
  longer quotes the request URL.
- **No false "429" rate limits**: rate-limit markers are no longer matched
  inside URLs or request paths (cursor and user ids such as `max_id=...3429...`);
  an HTTP 429 / `TooManyRequestsException` is still a rate limit. A feed
  refusal with such a cursor is reported as `feed_unavailable`.

- **Instagram session check**: the saved session is no longer verified with
  instaloader's `test_login()` (legacy GraphQL `query_hash` d6f4427…, which
  Instagram answers with 401 "Please wait a few minutes", and which reported
  every error as "not logged in"). The check now reads the `sessionid` /
  `ds_user_id` cookies and asks `api/v1/users/<id>/info/` once (single
  connection attempt). A throttled or failed check raises the new
  `InstagramSessionCheckFailed` (a subclass of `InstagramRateLimited`, exit
  code 3) and **never falls back to a password login**; the session file is
  left untouched. A password login (now only `check instagram --login`, see
  above) is only used when the session is positively logged out.
- **Instagram saved feed**: collected through the private API
  (`api/v1/feed/saved/posts/`, paginated with `max_id`) instead of
  `Profile.own_profile().get_saved_posts()`, which use legacy GraphQL
  `query_hash` queries. Owners, comment counts and carousel video children
  (with durations) are read from the private API media structs.
- `AbortDownloadException` (checkpoint, login redirect) during a run is mapped
  to `InstagramAuthRequired`.
- **Instagram saved feed via the web REST API**: with a web session the
  private-API feed on `i.instagram.com` (iPad headers) was answered with 200
  `"fail"` "We're sorry, but something went wrong" (and retried three times).
  The feed is now requested like the Instagram web app does it:
  `https://www.instagram.com/api/v1/feed/saved/posts/` with `X-IG-App-ID`,
  `X-CSRFToken` (from the `csrftoken` cookie), `X-Requested-With`,
  `X-ASBD-ID`, `X-IG-WWW-Claim` and the saved page as `Referer`, through
  instaloader's session (cookies, rate controller). New option
  `instagram.feed_api = "web" | "iphone"` (default `"web"`; invalid values are
  reported by `config validate` and fail the run with a clear message).
- **Instagram feed refusals are not retried**: feed pages get one attempt
  (network errors are still retried up to `max_connection_attempts`). A
  `"fail"` answer raises the new `InstagramFeedUnavailable` (a `RateLimited`
  subclass): CLI exit code 3 with a message that the session is fine, nothing
  was lost and which `instagram.feed_api` to try; report `stopped_reason` and
  job `error_code` `feed_unavailable`.
- **Instagram session outcome is shown**: `extract instagram` prints
  "Instagram session verified (no password login)"; API jobs get the same
  progress message.

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
