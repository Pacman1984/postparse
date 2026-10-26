"""
FastAPI dependency injection functions for PostParse API.

This module provides reusable dependencies for:
- Database connections with proper lifecycle management
- Taxonomy classifiers (cached per taxonomy spec hash and provider)
- JWT authentication (optional, configurable)
- Configuration management

Example:
    @app.get("/posts")
    async def get_posts(db: SocialMediaDatabase = Depends(get_db)):
        return db.get_instagram_posts()
"""

import os
import threading
from collections.abc import Callable
from functools import lru_cache
from typing import Any, Dict, Generator, Optional

from fastapi import Depends, HTTPException, WebSocket, WebSocketException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from jose import JWTError, jwt

from postparse.classification import TaxonomyClassifier, TaxonomySpec, load_taxonomies
from postparse.core.data.database import SocialMediaDatabase
from postparse.core.utils.config import ConfigManager
from postparse.llm.client import select_provider
from postparse.llm.config import LLMConfig
from postparse.api.services.job_manager import JobManager
from postparse.api.services.websocket_manager import WebSocketManager
from postparse.api.services.cache_manager import CacheManager
from postparse.api.services.extraction_service import (
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


#: Ad-hoc taxonomy behind the legacy ``/classify/recipe`` endpoints.
RECIPE_SPEC = TaxonomySpec.adhoc(
    {
        "recipe": "Cooking instructions, ingredients or a dish to prepare (food or drinks)",
        "not_recipe": "Anything else",
    },
    mode="single",
    name="recipe",
)

#: ``(spec, provider_name) -> TaxonomyClassifier``; override in tests.
ClassifierFactory = Callable[[TaxonomySpec, Optional[str]], TaxonomyClassifier]

_classifier_lock = threading.Lock()
_classifier_cache: Dict[tuple, TaxonomyClassifier] = {}


def get_cached_classifier(
    spec: TaxonomySpec,
    provider_name: Optional[str] = None,
    config_path: Optional[str] = None,
) -> TaxonomyClassifier:
    """
    Return a classifier cached per (spec hash, provider, config file).

    Building a classifier discovers the served model of self-hosted providers
    once; later requests reuse the instance.

    Args:
        spec: Taxonomy (configured or ad hoc).
        provider_name: Provider from ``[llm.providers]``; None for the default.
        config_path: Config file the providers are read from.

    Returns:
        TaxonomyClassifier: Cached classifier.

    Raises:
        ValueError: If the provider is unknown or the LLM config is invalid.
    """
    key = (spec.spec_sha256, (provider_name or "").lower() or None, config_path)
    with _classifier_lock:
        cached = _classifier_cache.get(key)
    if cached is not None:
        return cached
    config = ConfigManager(config_path) if config_path else get_config()
    llm_config = LLMConfig.from_config_manager(config)
    classifier = TaxonomyClassifier.from_provider(spec, select_provider(llm_config, provider_name))
    with _classifier_lock:
        return _classifier_cache.setdefault(key, classifier)


def clear_classifier_cache() -> None:
    """Forget cached classifiers (after config changes and in tests)."""
    with _classifier_lock:
        _classifier_cache.clear()


def get_classifier_factory(config: ConfigManager = Depends(get_config)) -> ClassifierFactory:
    """
    FastAPI dependency returning a classifier factory bound to the active config.

    Example:
        @router.post("/classify/multi")
        async def classify(factory: ClassifierFactory = Depends(get_classifier_factory)):
            classifier = factory(TaxonomySpec.adhoc(["a", "b"], mode="single"), None)
    """
    config_path = getattr(config, "config_path", None)

    def factory(spec: TaxonomySpec, provider_name: Optional[str] = None) -> TaxonomyClassifier:
        return get_cached_classifier(spec, provider_name, config_path)

    return factory


def get_taxonomies(config: ConfigManager = Depends(get_config)) -> Dict[str, TaxonomySpec]:
    """
    FastAPI dependency returning the configured taxonomies (``topics`` fallback included).
    """
    return load_taxonomies(config)


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


