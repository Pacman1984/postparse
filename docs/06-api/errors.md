# Error Handling

## HTTP Status Codes

| Code | Meaning |
|------|---------|
| 400 | Invalid request (validation, missing fields) |
| 401 | Unauthorized (invalid or missing token) |
| 404 | Resource not found |
| 429 | Rate limit exceeded |
| 500 | Internal server error |
| 503 | Service unavailable (LLM provider down) |

## Error Response Format

```json
{
  "error_code": "INVALID_REQUEST",
  "message": "Text field is required",
  "details": {"field": "text", "issue": "missing"}
}
```

## Common Error Codes

| Code | Cause |
|------|-------|
| `INVALID_REQUEST` | Validation failed |
| `UNAUTHORIZED` | Auth failed |
| `NOT_FOUND` | Job or resource not found |
| `RATE_LIMIT_EXCEEDED` | Too many requests (60/min default) |
| `LLM_PROVIDER_ERROR` | LLM service unavailable |
| `INTERNAL_ERROR` | Unexpected server error |

## Rate Limiting

- Default: 60 requests/minute per IP
- Burst: up to 10 extra
- Excluded: `/health`, `/docs`
