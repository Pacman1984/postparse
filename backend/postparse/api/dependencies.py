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

from functools import lru_cache
from typing import Generator, Optional, Dict, Any
from pathlib import Path

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from jose import JWTError, jwt

from backend.postparse.core.data.database import SocialMediaDatabase
from backend.postparse.services.analysis.classifiers.llm import RecipeLLMClassifier
from backend.postparse.core.utils.config import ConfigManager

# Security scheme for JWT authentication
security = HTTPBearer(auto_error=False)


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


@lru_cache()
def _get_cached_recipe_llm_classifier(config: ConfigManager) -> RecipeLLMClassifier:
    """
    Get cached RecipeLLMClassifier instance (internal helper).

    The LLM classifier is cached to avoid re-initialization on every request.
    Uses the default LLM provider from config.

    This is a non-FastAPI cached helper that should not be called directly
    in route handlers. Use get_recipe_llm_classifier instead.

    Args:
        config: ConfigManager instance.

    Returns:
        RecipeLLMClassifier: Cached LLM classifier instance.
    """
    provider_name = config.get("llm.default_provider", "ollama")
    return RecipeLLMClassifier(provider_name=provider_name)


def get_recipe_llm_classifier(config: ConfigManager = Depends(get_config)) -> RecipeLLMClassifier:
    """
    FastAPI dependency for RecipeLLMClassifier.

    Returns a cached LLM classifier instance. The caching is handled by
    _get_cached_recipe_llm_classifier to avoid conflicts with FastAPI's
    dependency injection mechanism.

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
    return _get_cached_recipe_llm_classifier(config)


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
    # Check if authentication is enabled
    auth_enabled = config.get("api.auth.enabled", False)
    if not auth_enabled:
        return None

    # If auth is enabled, token is required
    if not credentials:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication token is required",
            headers={"WWW-Authenticate": "Bearer"},
        )

    token = credentials.credentials

    # Get JWT configuration
    secret_key = config.get("api.auth.secret_key")
    if not secret_key:
        # Try environment variable
        import os
        secret_key = os.getenv("JWT_SECRET_KEY")
        if not secret_key:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="JWT secret key not configured",
            )

    algorithm = config.get("api.auth.algorithm", "HS256")

    try:
        # Decode and validate token
        payload = jwt.decode(token, secret_key, algorithms=[algorithm])
        return payload
    except JWTError as e:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"Invalid authentication token: {str(e)}",
            headers={"WWW-Authenticate": "Bearer"},
        )


def get_optional_auth(
    user: Optional[Dict[str, Any]] = Depends(get_current_user),
) -> Optional[Dict[str, Any]]:
    """
    Optional authentication dependency that doesn't raise errors.

    This is a convenience wrapper around get_current_user for endpoints
    that support both authenticated and anonymous access.

    Args:
        user: User info from get_current_user (injected dependency).

    Returns:
        User info dict if authenticated, None otherwise.

    Example:
        @app.get("/public")
        def public_route(user: Optional[Dict] = Depends(get_optional_auth)):
            if user:
                return {"message": f"Hello, {user['username']}"}
            return {"message": "Hello, guest"}
    """
    return user


