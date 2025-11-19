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
from typing import Callable, List, Optional
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
    Request/response logging middleware.

    Logs all incoming requests with:
    - Request ID (UUID for tracing)
    - Method and path
    - Client IP and user agent
    - Response status code
    - Processing time
    """

    def __init__(self, app, config: ConfigManager):
        """
        Initialize logging middleware.

        Args:
            app: FastAPI application instance.
            config: ConfigManager for reading log level.
        """
        super().__init__(app)
        self.config = config
        log_level = config.get("api.log_level", "info").upper()
        logger.setLevel(getattr(logging, log_level, logging.INFO))

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        """
        Process request and log details.

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

        # Log incoming request
        logger.info(
            f"[{request_id}] {request.method} {request.url.path} - "
            f"Client: {client_ip} - User-Agent: {user_agent}"
        )

        # Process request and measure time
        start_time = time.time()
        response = await call_next(request)
        processing_time = time.time() - start_time

        # Log response
        logger.info(
            f"[{request_id}] {request.method} {request.url.path} - "
            f"Status: {response.status_code} - Time: {processing_time:.3f}s"
        )

        # Add request ID to response headers
        response.headers["X-Request-ID"] = request_id
        response.headers["X-Processing-Time"] = f"{processing_time:.3f}"

        return response


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
    Rate limiting middleware (placeholder).

    This is a placeholder for future rate limiting implementation.
    Will use Redis or in-memory store for tracking request counts.

    TODO: Implement actual rate limiting in next phase.
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

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        """
        Process request and check rate limits (placeholder).

        Args:
            request: Incoming HTTP request.
            call_next: Next middleware/handler in chain.

        Returns:
            Response from next handler or 429 if rate limit exceeded.
        """
        # Skip if disabled
        if not self.enabled:
            return await call_next(request)

        # TODO: Implement actual rate limiting logic
        # For now, just pass through
        return await call_next(request)

