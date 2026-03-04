"""
FastAPI middleware for authentication, CORS, and request logging.

This module provides configurable middleware for:
- JWT authentication (optional, can be disabled for development)
- CORS configuration for frontend access
- Request/response logging with request IDs
- Rate limiting (placeholder for future implementation)
"""

import time
import uuid
import logging
import threading
import json
import re
import traceback
from typing import Callable, Optional, Dict, Any
from fastapi import HTTPException, Request, Response, status
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.base import BaseHTTPMiddleware

from backend.postparse.core.utils.config import ConfigManager
from backend.postparse.api.dependencies import extract_bearer_token, validate_jwt_token

logger = logging.getLogger(__name__)


class AuthenticationMiddleware(BaseHTTPMiddleware):
    """
    Optional JWT authentication middleware.

    Can be enabled/disabled via config. When enabled, validates JWT tokens
    from Authorization header. When disabled, allows all requests through.

    Public endpoints (health, docs) are always accessible without auth.
    """

    def __init__(self, app, config: ConfigManager):
        """
        Initialize authentication middleware.

        Args:
            app: FastAPI application instance.
            config: ConfigManager for reading auth configuration.
        """
        super().__init__(app)
        self.config = config
        self.enabled = config.get("api.auth.enabled", False)

        # Public endpoints that don't require authentication
        self.public_paths = {
            "/health",
            "/health/ready",
            "/health/live",
            "/metrics",
            "/docs",
            "/redoc",
            "/openapi.json",
        }

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        """
        Process request and validate authentication if enabled.

        Args:
            request: Incoming HTTP request.
            call_next: Next middleware/handler in chain.

        Returns:
            Response from next handler or 401 error if auth fails.
        """
        # Skip auth if disabled
        if not self.enabled:
            return await call_next(request)

        # Skip auth for public endpoints
        if request.url.path in self.public_paths:
            return await call_next(request)

        # Extract token from Authorization header
        auth_header = request.headers.get("Authorization")
        if not auth_header or not auth_header.startswith("Bearer "):
            return JSONResponse(
                status_code=status.HTTP_401_UNAUTHORIZED,
                content={
                    "error_code": "UNAUTHORIZED",
                    "message": "Missing or invalid Authorization header",
                },
                headers={"WWW-Authenticate": "Bearer"},
            )

        token = extract_bearer_token(auth_header)
        if not token:
            return JSONResponse(
                status_code=status.HTTP_401_UNAUTHORIZED,
                content={
                    "error_code": "UNAUTHORIZED",
                    "message": "Missing or invalid Authorization header",
                },
                headers={"WWW-Authenticate": "Bearer"},
            )

        # Validate token
        try:
            payload = validate_jwt_token(token, self.config)
            request.state.user = payload  # Store user info in request state
        except HTTPException as exc:
            error_code = (
                "UNAUTHORIZED"
                if exc.status_code == status.HTTP_401_UNAUTHORIZED
                else "INTERNAL_ERROR"
            )
            headers = (
                {"WWW-Authenticate": "Bearer"}
                if exc.status_code == status.HTTP_401_UNAUTHORIZED
                else None
            )
            return JSONResponse(
                status_code=exc.status_code,
                content={
                    "error_code": error_code,
                    "message": str(exc.detail),
                },
                headers=headers,
            )

        return await call_next(request)


class RequestLoggingMiddleware(BaseHTTPMiddleware):
    """
    Enhanced request/response logging middleware with structured JSON logging.

    Logs all incoming requests with:
    - Request ID (UUID for tracing)
    - Method and path
    - Client IP and user agent
    - Request/response bodies (truncated, optional)
    - Query parameters and filters
    - Response status code
    - Processing time
    - Cache status (if available)
    - Error details (for 4xx/5xx responses)
    """

    def __init__(self, app, config: ConfigManager):
        """
        Initialize logging middleware.

        Args:
            app: FastAPI application instance.
            config: ConfigManager for reading log level and logging options.
        """
        super().__init__(app)
        self.config = config
        log_level = config.get("api.log_level", "info").upper()
        logger.setLevel(getattr(logging, log_level, logging.INFO))
        
        # Get logging options from config
        self.log_request_body = config.get("api.log_request_body", default=False)
        self.log_response_body = config.get("api.log_response_body", default=False)
        self.log_format = config.get("api.log_format", default="text")
        
        # Configure JSON formatter if requested
        if self.log_format == "json":
            try:
                from pythonjsonlogger import jsonlogger
                json_handler = logging.StreamHandler()
                formatter = jsonlogger.JsonFormatter(
                    '%(asctime)s %(name)s %(levelname)s %(message)s'
                )
                json_handler.setFormatter(formatter)
                logger.handlers = [json_handler]
            except ImportError:
                logger.warning("python-json-logger not installed, using text format")
                self.log_format = "text"
    
    def _redact_sensitive_data(self, data: Any) -> Any:
        """
        Redact sensitive fields from log data recursively.

        Args:
            data: Value that may contain nested sensitive fields.

        Returns:
            Redacted value with sensitive fields replaced.

        Example:
            Input: {"user": {"token": "abc123"}, "tags": [{"api_key": "x"}]}
            Output: {"user": {"token": "***REDACTED***"}, "tags": [{"api_key": "***REDACTED***"}]}
        """
        sensitive_fields = {
            "password", "token", "secret", "api_key", "apikey",
            "authorization", "auth", "credential", "private_key"
        }

        if isinstance(data, dict):
            redacted: Dict[str, Any] = {}
            for key, value in data.items():
                key_lower = str(key).lower()
                if any(field in key_lower for field in sensitive_fields):
                    redacted[key] = "***REDACTED***"
                else:
                    redacted[key] = self._redact_sensitive_data(value)
            return redacted

        if isinstance(data, list):
            return [self._redact_sensitive_data(item) for item in data]

        return data

    def _truncate_for_log(self, value: str, max_length: int = 500) -> str:
        """
        Truncate long values before writing to logs.

        Args:
            value: String value to truncate.
            max_length: Maximum length of string before truncation.

        Returns:
            Truncated string with ellipsis when needed.
        """
        if len(value) <= max_length:
            return value
        return f"{value[:max_length]}..."

    def _is_json_content_type(self, content_type: str) -> bool:
        """
        Check whether request content type is JSON-compatible.

        Args:
            content_type: Raw request content-type header value.

        Returns:
            True when payload should be treated as JSON.
        """
        content_type_lower = content_type.lower()
        return (
            "application/json" in content_type_lower
            or "+json" in content_type_lower
        )

    def _is_sensitive_non_json_endpoint(self, path: str) -> bool:
        """
        Check whether endpoint path should skip non-JSON body logging.

        Args:
            path: HTTP request path.

        Returns:
            True for paths likely to carry credentials or secrets.
        """
        path_lower = path.lower()
        sensitive_extract_markers = (
            "/telegram/extract",
            "/instagram/extract",
            "/extract/telegram",
            "/extract/instagram",
        )
        sensitive_keywords = {
            "/auth",
            "/login",
            "/token",
            "/password",
            "/secret",
            "/credential",
        }
        if any(marker in path_lower for marker in sensitive_extract_markers):
            return True
        return any(keyword in path_lower for keyword in sensitive_keywords)

    def _mask_plain_text_payload(self, payload: str) -> str:
        """
        Conservatively mask likely secrets in non-JSON payloads.

        Args:
            payload: Decoded request payload.

        Returns:
            Payload with obvious credentials replaced.

        Example:
            Input: "token=abc123&note=test"
            Output: "token=***REDACTED***&note=test"
        """
        masked = payload

        masked = re.sub(
            r"(?i)(authorization\s*[:=]\s*bearer\s+)[^\s&]+",
            r"\1***REDACTED***",
            masked,
        )
        masked = re.sub(
            r'(?i)("(?:password|token|secret|api[_-]?key|api[_-]?hash|authorization|credential)"\s*:\s*)"[^"]*"',
            r'\1"***REDACTED***"',
            masked,
        )
        masked = re.sub(
            r"(?i)\b(password|token|secret|api[_-]?key|api[_-]?hash|authorization|credential)\b(\s*[:=]\s*)([^\s&]+)",
            lambda match: f"{match.group(1)}{match.group(2)}***REDACTED***",
            masked,
        )
        return masked
    
    async def _extract_request_body(self, request: Request) -> Optional[str]:
        """
        Extract request body, redact sensitive content, and truncate for logs.

        Args:
            request: FastAPI Request object.

        Returns:
            Redacted request body string or None.
        """
        if not self.log_request_body:
            return None

        if request.method in ["POST", "PUT", "PATCH"]:
            try:
                body = await request.body()
                if body:
                    body_str = body.decode("utf-8", errors="replace")
                    content_type = request.headers.get("content-type", "")

                    if self._is_json_content_type(content_type):
                        try:
                            parsed_body = json.loads(body_str)
                            redacted_body = self._redact_sensitive_data(parsed_body)
                            return self._truncate_for_log(
                                json.dumps(redacted_body, ensure_ascii=True)
                            )
                        except json.JSONDecodeError:
                            # Continue with conservative plaintext handling below.
                            pass

                    if self._is_sensitive_non_json_endpoint(request.url.path):
                        return None

                    masked_body = self._mask_plain_text_payload(body_str)
                    return self._truncate_for_log(masked_body)
            except Exception as e:
                logger.debug(f"Could not extract request body: {e}")

        return None
    
    def _extract_filters_from_params(self, request: Request) -> Dict[str, Any]:
        """
        Extract filter parameters from query string.
        
        Args:
            request: FastAPI Request object.
            
        Returns:
            Dictionary of filter parameters.
        """
        filters = {}
        query_params = dict(request.query_params)
        
        # Common filter fields
        filter_fields = {
            "hashtags", "date_range", "content_type", "owner_username",
            "channel_username", "limit", "cursor", "offset"
        }
        
        for field in filter_fields:
            if field in query_params:
                filters[field] = query_params[field]
        
        return filters

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        """
        Process request and log structured details.

        Args:
            request: Incoming HTTP request.
            call_next: Next middleware/handler in chain.

        Returns:
            Response from next handler with added request ID header.
        """
        # Generate request ID for tracing
        request_id = str(uuid.uuid4())
        request.state.request_id = request_id

        # Get client info
        client_ip = request.client.host if request.client else "unknown"
        user_agent = request.headers.get("user-agent", "unknown")
        
        # Extract request body if enabled
        request_body = await self._extract_request_body(request)
        
        # Extract filter parameters
        filters = self._extract_filters_from_params(request)

        # Process request and measure time
        start_time = time.time()
        
        try:
            response = await call_next(request)
            processing_time = time.time() - start_time
            
            # Extract cache status from response headers
            cache_status = response.headers.get("X-Cache-Status", None)
            
            # Build log data
            log_data = {
                "request_id": request_id,
                "method": request.method,
                "path": request.url.path,
                "status": response.status_code,
                "duration": round(processing_time, 3),
                "client_ip": client_ip,
                "user_agent": user_agent
            }
            
            if filters:
                log_data["filters"] = filters
            
            if cache_status:
                log_data["cache_status"] = cache_status
            
            if request_body:
                log_data["request_body"] = request_body
            
            # Extract response body for errors
            if response.status_code >= 400 and self.log_response_body:
                try:
                    # Response body extraction would require response streaming
                    # which is complex; skip for now but log error flag
                    log_data["is_error"] = True
                except Exception:
                    pass
            
            # Redact sensitive data before logging
            log_data = self._redact_sensitive_data(log_data)
            
            # Log with appropriate format
            if self.log_format == "json":
                logger.info(json.dumps(log_data))
            else:
                log_msg = (
                    f"[{request_id}] {request.method} {request.url.path} - "
                    f"Status: {response.status_code} - Time: {processing_time:.3f}s"
                )
                if cache_status:
                    log_msg += f" - Cache: {cache_status}"
                if filters:
                    log_msg += f" - Filters: {filters}"
                logger.info(log_msg)
            
            # Add request ID to response headers
            response.headers["X-Request-ID"] = request_id
            response.headers["X-Processing-Time"] = f"{processing_time:.3f}"
            
            return response
            
        except Exception as e:
            processing_time = time.time() - start_time
            
            # Log error with full details
            error_data = {
                "request_id": request_id,
                "method": request.method,
                "path": request.url.path,
                "status": 500,
                "duration": round(processing_time, 3),
                "client_ip": client_ip,
                "user_agent": user_agent,
                "error": str(e),
                "error_type": type(e).__name__
            }
            
            if filters:
                error_data["filters"] = filters
            
            # Add stack trace for 500 errors
            if isinstance(e, Exception):
                error_data["traceback"] = traceback.format_exc()
            
            # Redact sensitive data before logging
            error_data = self._redact_sensitive_data(error_data)
            
            if self.log_format == "json":
                logger.error(json.dumps(error_data))
            else:
                logger.error(
                    f"[{request_id}] {request.method} {request.url.path} - "
                    f"Error: {str(e)} - Time: {processing_time:.3f}s",
                    exc_info=True
                )
            
            # Re-raise the exception
            raise


def configure_cors(app, config: ConfigManager) -> None:
    """
    Configure CORS middleware for FastAPI app.

    Reads CORS settings from config and adds CORSMiddleware to app.

    Args:
        app: FastAPI application instance.
        config: ConfigManager for reading CORS configuration.

    Example:
        from fastapi import FastAPI
        from postparse.api.middleware import configure_cors

        app = FastAPI()
        config = ConfigManager()
        configure_cors(app, config)
    """
    # Get CORS configuration
    allowed_origins = config.get(
        "api.cors.allowed_origins",
        ["http://localhost:3000", "http://localhost:3001"]
    )
    allow_credentials = config.get("api.cors.allow_credentials", True)
    allowed_methods = config.get("api.cors.allowed_methods", ["*"])
    allowed_headers = config.get("api.cors.allowed_headers", ["*"])

    # Add CORS middleware
    app.add_middleware(
        CORSMiddleware,
        allow_origins=allowed_origins,
        allow_credentials=allow_credentials,
        allow_methods=allowed_methods,
        allow_headers=allowed_headers,
    )

    logger.info(f"CORS configured with origins: {allowed_origins}")


class RateLimitMiddleware(BaseHTTPMiddleware):
    """
    Rate limiting middleware using token bucket algorithm.

    Implements per-IP rate limiting with in-memory token buckets.
    For production multi-instance deployments, consider Redis-based storage.

    Attributes:
        config: Configuration manager.
        enabled: Whether rate limiting is active.
        requests_per_minute: Base rate limit per IP.
        burst_size: Additional burst capacity above base rate.
        _buckets: In-memory storage of token buckets per client IP.
        _lock: Thread-safe lock for bucket access.
        _cleanup_interval: Cleanup frequency in seconds.
        _last_cleanup: Timestamp of last cleanup.

    Example:
        Rate limit: 60 requests/minute with burst of 10
        Client can make up to 70 requests immediately, then 1 per second.
    """

    def __init__(self, app, config: ConfigManager):
        """
        Initialize rate limiting middleware.

        Args:
            app: FastAPI application instance.
            config: ConfigManager for reading rate limit configuration.
        """
        super().__init__(app)
        self.config = config
        self.enabled = config.get("api.rate_limiting.enabled", False)
        self.requests_per_minute = config.get("api.rate_limiting.requests_per_minute", 60)
        self.burst_size = config.get("api.rate_limiting.burst_size", 10)
        
        # In-memory storage for token buckets
        self._buckets: Dict[str, Dict[str, Any]] = {}
        self._lock = threading.Lock()
        self._cleanup_interval = 300  # Cleanup every 5 minutes
        self._last_cleanup = time.time()
        
        logger.info(
            f"Rate limiting initialized: enabled={self.enabled}, "
            f"rate={self.requests_per_minute}/min, burst={self.burst_size}"
        )

    def _check_rate_limit(self, client_ip: str) -> bool:
        """
        Check if request is allowed under rate limit using token bucket.

        Args:
            client_ip: Client IP address.

        Returns:
            True if request is allowed, False if rate limit exceeded.

        Example:
            allowed = self._check_rate_limit("192.168.1.1")
            if not allowed:
                return 429 response
        """
        current_time = time.time()
        
        with self._lock:
            # Get or create bucket for this IP
            if client_ip not in self._buckets:
                self._buckets[client_ip] = {
                    "tokens": self.requests_per_minute + self.burst_size,
                    "last_refill": current_time
                }
            
            bucket = self._buckets[client_ip]
            
            # Calculate time elapsed since last refill
            time_elapsed = current_time - bucket["last_refill"]
            
            # Refill tokens based on time elapsed
            # Rate: requests_per_minute tokens per 60 seconds
            tokens_to_add = (time_elapsed / 60.0) * self.requests_per_minute
            max_tokens = self.requests_per_minute + self.burst_size
            bucket["tokens"] = min(max_tokens, bucket["tokens"] + tokens_to_add)
            bucket["last_refill"] = current_time
            
            # Check if we have tokens available
            if bucket["tokens"] >= 1:
                bucket["tokens"] -= 1
                logger.debug(
                    f"Rate limit check for {client_ip}: allowed "
                    f"(tokens remaining: {bucket['tokens']:.2f})"
                )
                return True
            else:
                logger.warning(
                    f"Rate limit exceeded for {client_ip} "
                    f"(tokens: {bucket['tokens']:.2f})"
                )
                return False

    def _cleanup_old_buckets(self) -> None:
        """
        Remove inactive buckets to prevent memory leaks.

        Removes buckets for IPs that haven't made requests in over 1 hour.

        Example:
            Called periodically during request processing.
        """
        current_time = time.time()
        cutoff_time = current_time - 3600  # 1 hour ago
        
        with self._lock:
            buckets_to_remove = [
                ip for ip, bucket in self._buckets.items()
                if bucket["last_refill"] < cutoff_time
            ]
            
            for ip in buckets_to_remove:
                del self._buckets[ip]
            
            if buckets_to_remove:
                logger.info(
                    f"Cleaned up {len(buckets_to_remove)} inactive "
                    f"rate limit buckets"
                )
        
        self._last_cleanup = current_time

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        """
        Process request and enforce rate limits.

        Args:
            request: Incoming HTTP request.
            call_next: Next middleware/handler in chain.

        Returns:
            Response from next handler or 429 if rate limit exceeded.

        Example:
            Automatically applied to all requests via middleware.
        """
        # Skip if disabled
        if not self.enabled:
            return await call_next(request)
        
        # Extract client IP
        client_ip = request.client.host if request.client else "unknown"
        
        # Skip rate limiting for health endpoints
        if request.url.path in ["/health", "/health/ready", "/health/live"]:
            return await call_next(request)
        
        # Check rate limit
        if not self._check_rate_limit(client_ip):
            return JSONResponse(
                status_code=429,
                content={
                    "error_code": "RATE_LIMIT_EXCEEDED",
                    "message": "Too many requests. Please try again later.",
                    "details": {
                        "limit": self.requests_per_minute,
                        "window": "1 minute"
                    }
                }
            )
        
        # Periodic cleanup of old buckets
        current_time = time.time()
        if current_time - self._last_cleanup >= self._cleanup_interval:
            self._cleanup_old_buckets()
        
        return await call_next(request)

