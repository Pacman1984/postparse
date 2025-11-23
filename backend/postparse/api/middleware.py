"""
FastAPI middleware for authentication, CORS, and request logging.

This module provides configurable middleware for:
- JWT authentication (optional, can be disabled for development)
- CORS configuration for frontend access
- Request/response logging with request IDs
- Rate limiting (placeholder for future implementation)
"""

import os
import time
import uuid
import logging
import threading
import json
import traceback
from typing import Callable, List, Optional, Dict, Any
from fastapi import Request, Response, status
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.base import BaseHTTPMiddleware
from jose import JWTError, jwt

from backend.postparse.core.utils.config import ConfigManager

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
        self.secret_key = config.get("api.auth.secret_key") or os.getenv("JWT_SECRET_KEY")
        self.algorithm = config.get("api.auth.algorithm", "HS256")

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

        token = auth_header.replace("Bearer ", "")

        # Validate token
        try:
            if not self.secret_key:
                logger.error("JWT secret key not configured")
                return JSONResponse(
                    status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                    content={
                        "error_code": "INTERNAL_ERROR",
                        "message": "Authentication not properly configured",
                    },
                )

            payload = jwt.decode(token, self.secret_key, algorithms=[self.algorithm])
            request.state.user = payload  # Store user info in request state
        except JWTError as e:
            return JSONResponse(
                status_code=status.HTTP_401_UNAUTHORIZED,
                content={
                    "error_code": "UNAUTHORIZED",
                    "message": f"Invalid token: {str(e)}",
                },
                headers={"WWW-Authenticate": "Bearer"},
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
    
    def _redact_sensitive_data(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Redact sensitive fields from log data.
        
        Args:
            data: Dictionary that may contain sensitive data.
            
        Returns:
            Dictionary with sensitive fields redacted.
        """
        sensitive_fields = {
            "password", "token", "secret", "api_key", "apikey",
            "authorization", "auth", "credential", "private_key"
        }
        
        redacted = {}
        for key, value in data.items():
            key_lower = key.lower()
            if any(field in key_lower for field in sensitive_fields):
                redacted[key] = "***REDACTED***"
            elif isinstance(value, dict):
                redacted[key] = self._redact_sensitive_data(value)
            else:
                redacted[key] = value
        
        return redacted
    
    async def _extract_request_body(self, request: Request) -> Optional[str]:
        """
        Extract and truncate request body if logging is enabled.
        
        Args:
            request: FastAPI Request object.
            
        Returns:
            Truncated request body as string or None.
        """
        if not self.log_request_body:
            return None
        
        if request.method in ["POST", "PUT", "PATCH"]:
            try:
                body = await request.body()
                if body:
                    body_str = body.decode("utf-8")
                    # Truncate to 500 chars
                    return body_str[:500] + "..." if len(body_str) > 500 else body_str
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

