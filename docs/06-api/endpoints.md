# REST API Endpoints

Base URL: `http://localhost:8000/api/v1`

## Authentication

Optional. When enabled: `Authorization: Bearer YOUR_JWT_TOKEN`

## Endpoints

### Telegram

| Method | Endpoint | Purpose |
|--------|----------|---------|
| POST | `/telegram/extract` | Start extraction. Body: `api_id`, `api_hash`, `phone`, `limit`, `force_update` |
| GET | `/telegram/messages` | List messages. Query: `limit` (default 50, max 100) |
| GET | `/telegram/jobs/{job_id}` | Job status |

### Instagram

| Method | Endpoint | Purpose |
|--------|----------|---------|
| POST | `/instagram/extract` | Start extraction. Body: `username`, `password`, `limit`, `force_update`, `use_api` |
| GET | `/instagram/posts` | List posts. Query: `limit` |
| GET | `/instagram/jobs/{job_id}` | Job status |

### Classification

| Method | Endpoint | Purpose |
|--------|----------|---------|
| POST | `/classify/recipe` | Single recipe classification |
| POST | `/classify/batch` | Batch classification |
| POST | `/classify/multi` | Multi-class (custom categories) |
| POST | `/classify/multi/batch` | Batch multi-class |

### Search

| Method | Endpoint | Purpose |
|--------|----------|---------|
| GET | `/search/posts` | Search Instagram. Query: `hashtags`, `limit` |
| GET | `/search/messages` | Search Telegram. Query: `limit` |

### Jobs

| Method | Endpoint | Purpose |
|--------|----------|---------|
| GET | `/jobs/{job_id}` | Unified job status (all platforms) |

### Health

| Endpoint | Purpose |
|----------|---------|
| GET `/health` | Basic health |
| GET `/health/ready` | Readiness (DB + LLM) |
| GET `/metrics` | Request counts, stats |

## WebSocket Progress

**Endpoint:** `ws://localhost:8000/api/v1/jobs/ws/progress/{job_id}`

Works for all platforms. Connect after starting extraction via REST.

**Message format:**
```json
{
  "job_id": "uuid",
  "status": "pending|running|completed|failed",
  "progress": 0-100,
  "messages_processed": 65,
  "errors": [],
  "timestamp": "ISO8601"
}
```

**Lifecycle:** `pending` → `running` → `completed` or `failed`. Connection closes on completion.

**Error:** If job not found, sends `{"error": "Job {id} not found"}` then closes.

## Interactive Docs

- Swagger UI: http://localhost:8000/docs
- ReDoc: http://localhost:8000/redoc
