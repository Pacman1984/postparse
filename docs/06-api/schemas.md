# Request/Response Schemas

## Telegram Extract

**Request:** `api_id`, `api_hash`, `phone`, `limit`, `force_update`

**Response:** `job_id`, `status`, `message_count`

## Instagram Extract

**Request:** `username`, `password`, `limit`, `force_update`, `use_api`

**Response:** `job_id`, `status`, `post_count`

## Classify Recipe

**Request:** `text`, `classifier_type` (default `"llm"`), `provider_name`

**Response:** `label`, `confidence`, `details`, `processing_time`, `classifier_used`

## Classify Multi

**Request:** `text`, `classes` (dict), `provider_name`

**Response:** `label`, `confidence`, `reasoning`, `details`

## Error Response

```json
{
  "error_code": "INVALID_REQUEST",
  "message": "Text field is required",
  "details": {"field": "text", "issue": "missing"}
}
```

**Common codes:** `INVALID_REQUEST` (400), `UNAUTHORIZED` (401), `NOT_FOUND` (404), `RATE_LIMIT_EXCEEDED` (429), `LLM_PROVIDER_ERROR` (503)
