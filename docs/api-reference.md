# API reference

The REST API is a FastAPI application over the same services as the CLI. The
interactive documentation is served by the app itself: Swagger UI at `/docs`,
ReDoc at `/redoc`, the OpenAPI schema at `/openapi.json`.

## Starting the server

```bash
postparse serve                                  # host/port from [api], default 0.0.0.0:8000
postparse --config config/config.toml serve --port 8080
postparse serve --reload --log-level debug       # development
uvicorn postparse.api.main:create_app --factory --port 8000
```

* `postparse serve` loads `.env` (like every CLI command), sets
  `POSTPARSE_CONFIG` to the config file it found and starts uvicorn with
  `postparse.api.main:app`. The server processes inherit that environment.
* **Plain uvicorn does not load `.env`.** Export the credentials
  (`TELEGRAM_*`, `INSTAGRAM_*`, `OPENAI_API_KEY`, `JWT_SECRET_KEY`, ...) and
  optionally `POSTPARSE_CONFIG` before starting it.
* The services (database, jobs, cache, LLM clients) are built once in the
  lifespan. The database is created and migrated on startup if needed.
* **Run a single worker.** Jobs and their WebSocket subscribers live in the
  memory of one process; with `--workers N` a job started in one worker is
  unknown to the others (status requests answer 404).

## Endpoints

All application endpoints are below `/api/v1`. Job endpoints answer **202**
with `{job_id, job_type, status_url, websocket_url}`.

### Items, search and statistics

| Method | Path | Description |
|---|---|---|
| GET | `/api/v1/items` | Search and list items of both sources. Query: `q`, `source`, `tag`*, `author`*, `kind`*, `label`* (`taxonomy[:label]`), `date_from`, `date_to` (`YYYY-MM-DD`, UTC, inclusive), `has_transcript`, `cursor`, `limit` (default 50), `count` (default true), `offset` (deprecated). `*` = repeatable. |
| GET | `/api/v1/items/{item_id}` | One item with details, tags, media, transcripts, summary, links/fetches and current labels |
| GET | `/api/v1/items/{item_id}/transcript` | Transcripts of an item |
| GET | `/api/v1/items/{item_id}/summary` | Latest summary (404 when there is none) |
| GET | `/api/v1/stats` | Database statistics (`with_pending=false` skips pending classification counts) |
| GET | `/api/v1/taxonomies` | Configured and stored taxonomies with versions and result counts |
| GET | `/api/v1/search/posts` | Instagram posts (older response format): `hashtags`/`tags`, `start_date`, `end_date`, `content_type`, `owner_username`, `q`, `limit`, `cursor` |
| GET | `/api/v1/search/messages` | Telegram messages, same filters with `channel_username` |
| GET | `/api/v1/search/hashtags` | Hashtags with usage counts |

Pagination is keyset based: pass the response's `next_cursor` back as `cursor`.
Full-text syntax for `q`: words ANDed, `"phrase"`, `prefix*`; snippets mark hits
with `[...]`.

### Collection

| Method | Path | Description |
|---|---|---|
| POST | `/api/v1/telegram/extract` | Start a `telegram_extract` job. Body: `api_id`, `api_hash`, `phone` (override the env variables), `limit` (100), `force_update`. Never interactive: log in once with `postparse extract telegram`; the session in `sessions_dir` is reused. |
| GET | `/api/v1/telegram/messages`, `/api/v1/telegram/messages/{message_id}` | Saved Telegram messages |
| POST | `/api/v1/instagram/extract` | Start an `instagram_extract` job. Body: `username`, `password` (optional with a valid session), `limit` (50), `force_update`, `stop_after_known` (20), `refresh_dates`. `use_api=true` is not supported (400). |
| GET | `/api/v1/instagram/posts`, `/api/v1/instagram/posts/{shortcode}` | Saved Instagram posts (`offset` deprecated, use `cursor`) |

### Processing jobs

| Method | Path | Body (defaults) | CLI equivalent |
|---|---|---|---|
| POST | `/api/v1/transcription/run` | `source` (`instagram`), `limit` (50), `backend`, `refetch` (true), `item_ids` | `transcribe run` |
| GET | `/api/v1/transcription/status` | – | `transcribe status` |
| POST | `/api/v1/summaries/run` | `limit` (20), `provider`, `force`, `item_ids` | `summarize run` |
| POST | `/api/v1/enrichment/run` | `source` (`all`), `limit` (100), `force`, `refresh_legacy` (true), `domains` | `enrich run` |
| GET | `/api/v1/enrichment/status` | query `source`, `top_domains` (15) | `enrich status` |
| POST | `/api/v1/classify/run` | `taxonomy` (required), `scope` (`default`/`backfill`/`reprocess`), `limit`, `provider`, `wait_for_transcripts` (true), `filters` (`q`, `source`, `tags`, `authors`, `kinds`, `labels`, `date_from`, `date_to`, `has_transcript`) | `classify run` |

### Classification

| Method | Path | Description |
|---|---|---|
| POST | `/api/v1/classify/{taxonomy}` | Classify `text` into a configured or stored taxonomy. `persist=true` with `item_id` stores the result as a classification run. Optional `provider_name`. |
| POST | `/api/v1/classify/{taxonomy}/batch` | Up to 100 `texts`; with `persist=true`, `item_ids` (same length) are required |
| POST | `/api/v1/classify/recipe`, `/batch` | Ad-hoc single-label `recipe` / `not_recipe` |
| POST | `/api/v1/classify/multi`, `/multi/batch` | Ad-hoc single-label taxonomy from the request `classes` (default: labels of `topics`) |
| POST | `/api/v1/classify/multilabel`, `/multilabel/batch` | The same as multi-label |
| GET | `/api/v1/classify/classifiers` | Configured taxonomies and providers |

Batch responses list every input as `{input_index, ok, result | error}`; one
failing input never fails the request. The names `recipe`, `batch`, `multi`,
`multilabel`, `classifiers` and `run` are fixed routes, so taxonomies with these
names cannot be addressed through `/classify/{taxonomy}`. Ad-hoc endpoints never
store anything.

### Jobs

| Method | Path | Description |
|---|---|---|
| GET | `/api/v1/jobs` | Recent jobs (`job_type` filter) |
| GET | `/api/v1/jobs/{job_id}` | Status of any job |
| WS | `/api/v1/jobs/{job_id}/ws` | Live progress of any job |
| GET / WS | `/api/v1/telegram/jobs/{job_id}`, `/api/v1/instagram/jobs/{job_id}`, `/api/v1/{telegram,instagram}/ws/progress/{job_id}`, `/api/v1/jobs/ws/progress/{job_id}` | Older aliases, kept for compatibility |

### Health

| Method | Path | Description |
|---|---|---|
| GET | `/health` | Always 200 while the process runs; cheap database summary once the services are up |
| GET | `/health/ready` | Database (schema current, FTS index in sync), LLM providers (cached briefly; `llm=false` skips) and transcription backend (no model load); **503** when the database is not usable |
| GET | `/health/live` | Liveness probe, no checks |
| GET | `/metrics` | Item counts per source, job counts |
| GET | `/` | Links to docs and endpoint groups |

## Jobs

Job kinds: `telegram_extract`, `instagram_extract`, `transcribe`, `summarize`,
`enrich`, `classify`. `JobRunner` runs each job as an asyncio task; blocking
work (Instagram, transcription, enrichment) runs in a worker thread, Telegram,
classification and summaries on the event loop.

A job (status endpoint and every WebSocket message) looks like:

```json
{
  "job_id": "…", "job_type": "transcribe", "status": "running",
  "progress": 40, "messages_processed": 20, "total": 50, "message": "…",
  "errors": [], "error_code": null, "result": null,
  "started_at": "…", "finished_at": null
}
```

`status` is `pending`, `running`, `completed` or `failed`; `result` holds the
service report when the job ends. A job **fails** with an `error_code` when the
service raises or its report stops for a hard reason:

| `error_code` | Cause |
|---|---|
| `credentials_missing` | `TELEGRAM_*` / `INSTAGRAM_*` not set and not in the request |
| `auth_required` | session invalid, login code / 2FA needed (log in once via the CLI) |
| `rate_limited` | Telegram FloodWait above the threshold, Instagram 429 |
| `feed_unavailable` | Instagram refused the saved feed with a `"fail"` status ("something went wrong"); the session is fine, see `instagram.feed_api` |
| `suspected_block` | transcription stopped by the soft-block circuit breaker |
| `backend_unavailable` | ASR backend not installed or unreachable |
| `llm_error` | classification / summarization failed at the LLM |
| `invalid_request` | unknown taxonomy, bad parameters |
| `cancelled` | the server shut down while the job ran |
| `internal_error` | anything else |

The response cache is invalidated after every job. Finished jobs are dropped
after `api.jobs.max_job_age_hours` (24) by a cleanup task running every
`cleanup_interval_minutes` (60).

## WebSocket

Connect to `ws://host:8000/api/v1/jobs/{job_id}/ws`. The server sends the
current job state immediately and then one message per progress event (the job
JSON above plus a `timestamp`). Unknown jobs get one
`{"error": "Job … not found", "job_id": …}` message and the socket is closed.
With authentication enabled, pass the token as `Authorization: Bearer …` header
or `?token=…` query parameter; missing or invalid tokens close the socket with
code 1008.

## Errors

Every error has a JSON body with an `error_code`:

| HTTP | `error_code` | Body |
|---|---|---|
| 4xx/5xx from routes | `HTTP_<status>` (e.g. `HTTP_404`) | `{error_code, detail}` |
| 400 | `HTTP_400` | invalid cursor, dates, labels or kinds |
| 401 | `UNAUTHORIZED` | `{error_code, message}`; missing/invalid bearer token |
| 422 | `VALIDATION_ERROR` | `{error_code, detail, errors: [{type, loc, msg, input, ctx}]}` |
| 429 | `RATE_LIMIT_EXCEEDED` | rate limit of `[api.rate_limiting]` exceeded |
| 503 | `LLM_PROVIDER_ERROR` | `{error_code, message, details}`; LLM provider unreachable |
| 500 | `INTERNAL_ERROR` | `{error_code, message}`; the exception text is hidden when `api.environment = "production"` |

## Authentication

Optional JWT bearer authentication (`[api.auth] enabled = true`):

* Every HTTP request needs `Authorization: Bearer <token>` except `/`, `/health`,
  `/health/ready`, `/health/live`, `/metrics`, `/docs`, `/redoc`,
  `/openapi.json`.
* Tokens are validated with `api.auth.secret_key` or, when that is not set, the
  `JWT_SECRET_KEY` environment variable, using `api.auth.algorithm` (`HS256`).
  Without any secret, protected requests fail with 500.
* PostParse does **not** issue tokens; create them with your own tooling
  (any JWT library, the same secret and algorithm).

## Rate limiting, CORS, cache, logging

* `[api.rate_limiting]`: token bucket per client IP, `requests_per_minute` (60)
  plus `burst_size` (10). Off by default.
* `[api.cors]`: `allowed_origins` (default `http://localhost:3000`, `:3001`),
  `allow_credentials`, `allowed_methods`, `allowed_headers`.
* `[api.cache]`: caches search and list responses (`X-Cache-Status: HIT|MISS`)
  in Redis (`redis_url`) or, when Redis is unreachable, in memory
  (`max_entries`). TTLs `default_ttl` (300 s) and `search_ttl` (600 s). Jobs and
  persisted classifications invalidate it. Off by default.
* Request logging: `api.log_level`, `api.log_format` (`text` / `json`),
  `api.log_request_body`, `api.log_response_body`.

## Example

```bash
# Start a transcription job and follow it
curl -s -X POST localhost:8000/api/v1/transcription/run \
     -H 'Content-Type: application/json' -d '{"limit": 10}'
curl -s localhost:8000/api/v1/jobs/<job_id>

# Search
curl -s 'localhost:8000/api/v1/items?q=pasta&label=topics:recipe&limit=5'

# Classify a text into "topics" and store it for item 42
curl -s -X POST localhost:8000/api/v1/classify/topics \
     -H 'Content-Type: application/json' \
     -d '{"text": "Carbonara mit Guanciale", "persist": true, "item_id": 42}'
```
