"""
Unit tests for API middleware request-body logging behavior.

These tests verify that request-body logging redacts sensitive values for JSON
payloads, skips non-JSON body logging for sensitive endpoints, and applies
conservative masking for non-JSON payloads on non-sensitive routes.
"""

import json
from typing import Any, Dict, Optional

import pytest
from fastapi import FastAPI
from starlette.requests import Request
from starlette.types import Message, Scope

from backend.postparse.api.middleware import RequestLoggingMiddleware


class _StaticConfig:
    """Simple config stub for middleware unit tests."""

    def __init__(self, values: Optional[Dict[str, Any]] = None) -> None:
        """
        Initialize static config values.

        Args:
            values: Optional dict of config key-value pairs.
        """
        self._values = values or {}

    def get(
        self,
        key: str,
        default: Optional[Any] = None,
        env_var: Optional[str] = None,
    ) -> Any:
        """
        Return a configured value for a key.

        Args:
            key: Dotted config key.
            default: Value to return if key is missing.
            env_var: Optional env var name (unused in stub).

        Returns:
            Configured value or default.
        """
        _ = env_var
        return self._values.get(key, default)


def _build_request(
    method: str,
    path: str,
    body: bytes,
    content_type: str,
) -> Request:
    """
    Create a Starlette request object with a predefined body.

    Args:
        method: HTTP method for the request.
        path: URL path.
        body: Raw request body bytes.
        content_type: Content type header value.

    Returns:
        Request object suitable for middleware helper tests.
    """
    scope: Scope = {
        "type": "http",
        "http_version": "1.1",
        "method": method,
        "scheme": "http",
        "path": path,
        "raw_path": path.encode("utf-8"),
        "query_string": b"",
        "headers": [(b"content-type", content_type.encode("utf-8"))],
        "client": ("127.0.0.1", 12345),
        "server": ("testserver", 80),
    }
    has_emitted_body = False

    async def receive() -> Message:
        nonlocal has_emitted_body
        if has_emitted_body:
            return {"type": "http.request", "body": b"", "more_body": False}
        has_emitted_body = True
        return {"type": "http.request", "body": body, "more_body": False}

    return Request(scope, receive)


@pytest.fixture
def request_logging_middleware() -> RequestLoggingMiddleware:
    """
    Build middleware with request-body logging enabled.

    Returns:
        Configured RequestLoggingMiddleware instance.
    """
    config = _StaticConfig(
        {
            "api.log_level": "info",
            "api.log_request_body": True,
            "api.log_response_body": False,
            "api.log_format": "text",
        }
    )
    return RequestLoggingMiddleware(FastAPI(), config)  # type: ignore[arg-type]


class TestRequestLoggingMiddlewareBodyHandling:
    """Tests for safe request-body extraction and redaction."""

    def test_is_sensitive_non_json_endpoint_matches_prefixed_extract_routes(
        self,
        request_logging_middleware: RequestLoggingMiddleware,
    ) -> None:
        """
        Verify sensitive endpoint detection for real API-prefixed extract paths.

        The middleware should flag extraction routes that include versioned API
        prefixes instead of relying on shortened test-only route literals.
        """
        assert request_logging_middleware._is_sensitive_non_json_endpoint(
            "/api/v1/telegram/extract"
        )
        assert request_logging_middleware._is_sensitive_non_json_endpoint(
            "/api/v1/instagram/extract"
        )

    @pytest.mark.asyncio
    async def test_extract_request_body_redacts_nested_json_fields(
        self,
        request_logging_middleware: RequestLoggingMiddleware,
    ) -> None:
        """
        Verify recursive JSON redaction for nested dicts and list items.

        Sensitive keys should be replaced with redacted placeholders before
        serializing and returning the log payload.
        """
        payload = {
            "username": "alice",
            "password": "plain-secret",
            "meta": {"api_key": "top-secret"},
            "items": [{"token": "token-value", "safe": "ok"}],
        }
        request = _build_request(
            method="POST",
            path="/classify",
            body=json.dumps(payload).encode("utf-8"),
            content_type="application/json",
        )

        logged_body = await request_logging_middleware._extract_request_body(request)

        assert logged_body is not None
        parsed_body = json.loads(logged_body)
        assert parsed_body["username"] == "alice"
        assert parsed_body["password"] == "***REDACTED***"
        assert parsed_body["meta"]["api_key"] == "***REDACTED***"
        assert parsed_body["items"][0]["token"] == "***REDACTED***"
        assert parsed_body["items"][0]["safe"] == "ok"

    @pytest.mark.asyncio
    async def test_extract_request_body_skips_sensitive_non_json_endpoint(
        self,
        request_logging_middleware: RequestLoggingMiddleware,
    ) -> None:
        """
        Verify non-JSON bodies are not logged on sensitive endpoints.

        This ensures potentially credential-bearing payloads are dropped
        instead of logged.
        """
        request = _build_request(
            method="POST",
            path="/api/v1/telegram/extract",
            body=b"api_hash=abc123&password=secret",
            content_type="application/x-www-form-urlencoded",
        )

        logged_body = await request_logging_middleware._extract_request_body(request)

        assert logged_body is None

    @pytest.mark.asyncio
    async def test_extract_request_body_masks_non_json_payload(
        self,
        request_logging_middleware: RequestLoggingMiddleware,
    ) -> None:
        """
        Verify conservative masking for non-sensitive non-JSON payloads.

        Plaintext key/value secrets should be replaced before logging.
        """
        request = _build_request(
            method="POST",
            path="/classify",
            body=b"token=abc123&api_hash=hash123&note=hello",
            content_type="application/x-www-form-urlencoded",
        )

        logged_body = await request_logging_middleware._extract_request_body(request)

        assert logged_body is not None
        assert "***REDACTED***" in logged_body
        assert "abc123" not in logged_body
        assert "hash123" not in logged_body
        assert "note=hello" in logged_body
