"""
FastAPI dependency injection functions for PostParse API.

This module provides reusable dependencies for:
- Database connections with proper lifecycle management
- Classifier instances (cached for performance)
- JWT authentication (optional, configurable)
- Configuration management

Example:
    @app.get("/posts")
    async def get_posts(db: SocialMediaDatabase = Depends(get_db)):
        return db.get_instagram_posts()
"""

import os
from functools import lru_cache
from typing import Any, Dict, Generator, Optional

from fastapi import Depends, HTTPException, WebSocket, WebSocketException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from jose import JWTError, jwt

from backend.postparse.core.data.database import SocialMediaDatabase
from backend.postparse.services.analysis.classifiers.llm import RecipeLLMClassifier
from backend.postparse.core.utils.config import ConfigManager
from backend.postparse.api.services.job_manager import JobManager
from backend.postparse.api.services.websocket_manager import WebSocketManager
from backend.postparse.api.services.cache_manager import CacheManager
from backend.postparse.api.services.extraction_service import (
    TelegramExtractionService,
    InstagramExtractionService,
)

# Security scheme for JWT authentication
security = HTTPBearer(auto_error=False)


def _is_auth_enabled(config: ConfigManager) -> bool:
    """
    Determine whether API authentication is enabled.

    Args:
        config: Configuration manager instance.

    Returns:
        True when JWT authentication is enabled, otherwise False.
    """
    return bool(config.get("api.auth.enabled", False))


def extract_bearer_token(authorization_header: Optional[str]) -> Optional[str]:
    """
    Extract a bearer token from an Authorization header value.

    Args:
        authorization_header: Raw Authorization header value.

    Returns:
        Token string when header is a valid Bearer token, otherwise None.

    Example:
        token = extract_bearer_token("Bearer my.jwt.token")
    """
    if not authorization_header:
        return None

    if not authorization_header.startswith("Bearer "):
        return None

    token = authorization_header.replace("Bearer ", "", 1).strip()
    return token or None


def validate_jwt_token(token: str, config: ConfigManager) -> Dict[str, Any]:
    """
    Validate a JWT token using configured API authentication settings.

    Args:
        token: JWT token string to validate.
        config: Configuration manager instance.

    Returns:
        Decoded JWT payload dictionary.

    Raises:
        HTTPException: If JWT settings are invalid or token is invalid.

    Example:
        payload = validate_jwt_token("eyJhbGciOiJIUzI1NiIs...", config)
    """
    secret_key = config.get("api.auth.secret_key") or os.getenv("JWT_SECRET_KEY")
    if not secret_key:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="JWT secret key not configured",
        )

    algorithm = config.get("api.auth.algorithm", "HS256")

    try:
        return jwt.decode(token, secret_key, algorithms=[algorithm])
    except JWTError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"Invalid authentication token: {str(exc)}",
            headers={"WWW-Authenticate": "Bearer"},
        ) from exc


def _resolve_websocket_token(websocket: WebSocket) -> Optional[str]:
    """
    Resolve bearer token for WebSocket authentication.

    Args:
        websocket: Incoming WebSocket connection.

    Returns:
        Bearer token from Authorization header or `token` query param.
    """
    header_token = extract_bearer_token(websocket.headers.get("Authorization"))
    if header_token:
        return header_token
    return websocket.query_params.get("token")


@lru_cache()
def get_config() -> ConfigManager:
    """
    Get cached ConfigManager instance.

    Returns:
        ConfigManager: Singleton configuration manager instance.

    Example:
        config = get_config()
        db_path = config.get('database.default_db_path')
    """
    return ConfigManager()


def get_db(config: ConfigManager = Depends(get_config)) -> Generator[SocialMediaDatabase, None, None]:
    """
    Provide SocialMediaDatabase instance with proper lifecycle management.

    This dependency ensures the database connection is opened at request start
    and properly closed after the response is sent.

    Args:
        config: ConfigManager instance (injected dependency).

    Yields:
        SocialMediaDatabase: Database instance for the request.

    Example:
        @app.get("/posts")
        def get_posts(db: SocialMediaDatabase = Depends(get_db)):
            return db.get_instagram_posts()
    """
    db_path = config.get("database.default_db_path", "data/social_media.db")
    db = SocialMediaDatabase(db_path)
    try:
        yield db
    finally:
        # Database uses context manager pattern, no explicit close needed
        pass


@lru_cache(maxsize=8)
def _get_cached_recipe_llm_classifier(provider_name: str) -> RecipeLLMClassifier:
    """
    Get cached RecipeLLMClassifier instance (internal helper).

    The LLM classifier is cached to avoid re-initialization on every request.
    Caching is keyed by provider_name to ensure stability across ConfigManager instances.

    This is a non-FastAPI cached helper that should not be called directly
    in route handlers. Use get_recipe_llm_classifier instead.

    Args:
        provider_name: Name of the LLM provider (e.g., "ollama", "openai").

    Returns:
        RecipeLLMClassifier: Cached LLM classifier instance for the specified provider.
    """
    return RecipeLLMClassifier(provider_name=provider_name)


def get_recipe_llm_classifier(config: ConfigManager = Depends(get_config)) -> RecipeLLMClassifier:
    """
    FastAPI dependency for RecipeLLMClassifier.

    Returns a cached LLM classifier instance. The caching is handled by
    _get_cached_recipe_llm_classifier with provider_name as the cache key
    to ensure consistent caching across different ConfigManager instances.

    Args:
        config: ConfigManager instance (injected dependency).

    Returns:
        RecipeLLMClassifier: Cached LLM classifier instance.

    Example:
        @app.post("/classify/llm")
        def classify_llm(
            text: str,
            classifier: RecipeLLMClassifier = Depends(get_recipe_llm_classifier)
        ):
            return classifier.predict(text)
    """
    provider_name = config.get("llm.default_provider", "ollama")
    return _get_cached_recipe_llm_classifier(provider_name)


async def get_current_user(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(security),
    config: ConfigManager = Depends(get_config),
) -> Optional[Dict[str, Any]]:
    """
    Validate JWT token and return user information.

    This dependency is optional and can be disabled via config.
    When auth is disabled, it returns None.
    When enabled, it validates the JWT token and extracts user info.

    Args:
        credentials: HTTP Bearer token from request header.
        config: ConfigManager instance (injected dependency).

    Returns:
        Dict with user info if token is valid, None if auth is disabled.

    Raises:
        HTTPException: 401 Unauthorized if token is invalid or missing.

    Example:
        @app.get("/protected")
        def protected_route(user: Dict = Depends(get_current_user)):
            return {"user": user}
    """
    if not _is_auth_enabled(config):
        return None

    if not credentials:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication token is required",
            headers={"WWW-Authenticate": "Bearer"},
        )

    return validate_jwt_token(credentials.credentials, config)


async def get_current_websocket_user(
    websocket: WebSocket,
    config: ConfigManager = Depends(get_config),
) -> Optional[Dict[str, Any]]:
    """
    Validate WebSocket authentication using the same JWT rules as HTTP.

    Args:
        websocket: Incoming WebSocket connection.
        config: ConfigManager instance (injected dependency).

    Returns:
        Decoded JWT payload if authentication succeeds, or None when auth is
        disabled.

    Raises:
        WebSocketException: If authentication is enabled and token is missing
            or invalid.

    Example:
        @router.websocket("/ws/progress/{job_id}")
        async def ws(job_id: str, _: Dict[str, Any] = Depends(get_current_websocket_user)):
            ...
    """
    if not _is_auth_enabled(config):
        return None

    token = _resolve_websocket_token(websocket)
    if not token:
        raise WebSocketException(
            code=status.WS_1008_POLICY_VIOLATION,
            reason="Authentication token is required",
        )

    try:
        return validate_jwt_token(token, config)
    except HTTPException as exc:
        raise WebSocketException(
            code=status.WS_1008_POLICY_VIOLATION,
            reason=str(exc.detail),
        ) from exc


def get_optional_auth(
    user: Optional[Dict[str, Any]] = Depends(lambda: None),
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(security),
    config: ConfigManager = Depends(get_config),
) -> Optional[Dict[str, Any]]:
    """
    Optional authentication dependency that doesn't raise errors.

    Attempts to validate a Bearer token when authentication is enabled.
    Returns None when no credentials are provided or when validation fails,
    allowing endpoints to support both authenticated and anonymous access.

    Args:
        credentials: HTTP Bearer token from request header (optional).
        config: ConfigManager instance (injected dependency).

    Returns:
        User info dict if authenticated, None otherwise.

    Example:
        @app.get("/public")
        def public_route(user: Optional[Dict] = Depends(get_optional_auth)):
            if user:
                return {"message": f"Hello, {user['username']}"}
            return {"message": "Hello, guest"}
    """
    # Preserve direct-call compatibility (used in unit tests).
    # Only accept explicit dict overrides; ignore DI sentinel objects.
    if isinstance(user, dict):
        return user

    # When called directly (outside FastAPI DI), credentials may be a Depends
    # sentinel rather than an HTTPAuthorizationCredentials instance.
    if not isinstance(credentials, HTTPAuthorizationCredentials):
        return None

    if not _is_auth_enabled(config):
        return None

    try:
        return validate_jwt_token(credentials.credentials, config)
    except HTTPException:
        # Suppress auth errors for optional auth; treat as anonymous
        return None


@lru_cache()
def get_job_manager() -> JobManager:
    """
    Get singleton JobManager instance.

    Returns:
        JobManager: Singleton job manager instance.

    Example:
        @app.get("/jobs")
        def list_jobs(job_manager: JobManager = Depends(get_job_manager)):
            return job_manager.list_jobs()
    """
    return JobManager()


@lru_cache()
def get_websocket_manager() -> WebSocketManager:
    """
    Get singleton WebSocketManager instance.

    Returns:
        WebSocketManager: Singleton WebSocket manager instance.

    Example:
        @app.websocket("/ws/{job_id}")
        async def websocket_endpoint(
            job_id: str,
            ws_manager: WebSocketManager = Depends(get_websocket_manager)
        ):
            await ws_manager.connect(job_id, websocket)
    """
    return WebSocketManager()


@lru_cache()
def get_cache_manager() -> CacheManager:
    """
    Get singleton CacheManager instance.

    Returns:
        CacheManager: Singleton cache manager instance.

    Example:
        @app.get("/search/posts")
        async def search_posts(
            cache: CacheManager = Depends(get_cache_manager),
            db: SocialMediaDatabase = Depends(get_db)
        ):
            cache_key = cache.generate_cache_key("posts", hashtag="recipe")
            cached = cache.get(cache_key)
            if cached:
                return cached
            results = db.get_posts_by_hashtag("recipe")
            cache.set(cache_key, results, ttl=600)
            return results
    """
    config = get_config()
    return CacheManager(config)


def get_telegram_extraction_service(
    job_manager: JobManager = Depends(get_job_manager),
    ws_manager: WebSocketManager = Depends(get_websocket_manager),
    db: SocialMediaDatabase = Depends(get_db),
) -> TelegramExtractionService:
    """
    Get TelegramExtractionService with injected dependencies.

    Args:
        job_manager: JobManager instance (injected dependency).
        ws_manager: WebSocketManager instance (injected dependency).
        db: SocialMediaDatabase instance (injected dependency).

    Returns:
        TelegramExtractionService: Extraction service instance.

    Example:
        @app.post("/telegram/extract")
        async def extract(
            service: TelegramExtractionService = Depends(get_telegram_extraction_service)
        ):
            await service.run_extraction(...)
    """
    return TelegramExtractionService(job_manager, ws_manager, db)


def get_instagram_extraction_service(
    job_manager: JobManager = Depends(get_job_manager),
    ws_manager: WebSocketManager = Depends(get_websocket_manager),
    db: SocialMediaDatabase = Depends(get_db),
) -> InstagramExtractionService:
    """
    Get InstagramExtractionService with injected dependencies.

    Args:
        job_manager: JobManager instance (injected dependency).
        ws_manager: WebSocketManager instance (injected dependency).
        db: SocialMediaDatabase instance (injected dependency).

    Returns:
        InstagramExtractionService: Extraction service instance.

    Example:
        @app.post("/instagram/extract")
        async def extract(
            service: InstagramExtractionService = Depends(get_instagram_extraction_service)
        ):
            await service.run_extraction(...)
    """
    return InstagramExtractionService(job_manager, ws_manager, db)


