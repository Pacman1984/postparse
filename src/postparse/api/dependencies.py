"""FastAPI dependencies: authentication plus re-exports of :mod:`postparse.api.deps`.

Service dependencies (``get_query_service``, ``get_job_runner``, ...) live in
:mod:`postparse.api.deps` and read the service container from
``app.state.services``. This module adds the optional JWT authentication and
the classifier helpers of the legacy ``/classify`` endpoints.

Example:
    @router.get("/protected")
    def protected(user: dict | None = Depends(get_current_user)):
        return {"user": user}
"""

from __future__ import annotations

import os
from collections.abc import Callable
from typing import Any

import jwt
from fastapi import Depends, HTTPException, WebSocket, WebSocketException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from postparse.api.deps import (
    ApiServices,
    get_cache_manager,
    get_classification_service,
    get_config,
    get_enrichment_service,
    get_extraction_service,
    get_job_manager,
    get_job_runner,
    get_query_service,
    get_services,
    get_settings,
    get_summarization_service,
    get_transcription_service,
    get_websocket_manager,
)
from postparse.classification import TaxonomyClassifier, TaxonomySpec
from postparse.services.classification import ClassificationService

__all__ = [
    "RECIPE_SPEC",
    "ApiServices",
    "ClassifierFactory",
    "extract_bearer_token",
    "get_cache_manager",
    "get_classification_service",
    "get_classifier_factory",
    "get_config",
    "get_current_user",
    "get_current_websocket_user",
    "get_enrichment_service",
    "get_extraction_service",
    "get_job_manager",
    "get_job_runner",
    "get_optional_auth",
    "get_query_service",
    "get_services",
    "get_settings",
    "get_summarization_service",
    "get_taxonomies",
    "get_transcription_service",
    "get_websocket_manager",
    "validate_jwt_token",
]

# Security scheme for JWT authentication
security = HTTPBearer(auto_error=False)


def _is_auth_enabled(config: Any) -> bool:
    """Return True when ``[api.auth] enabled`` is set."""
    return bool(config is not None and config.get("api.auth.enabled", False))


def extract_bearer_token(authorization_header: str | None) -> str | None:
    """
    Extract a bearer token from an Authorization header value.

    Args:
        authorization_header: Raw Authorization header value.

    Returns:
        Token string when header is a valid Bearer token, otherwise None.

    Example:
        token = extract_bearer_token("Bearer my.jwt.token")
    """
    if not authorization_header or not authorization_header.startswith("Bearer "):
        return None
    token = authorization_header.replace("Bearer ", "", 1).strip()
    return token or None


def validate_jwt_token(token: str, config: Any) -> dict[str, Any]:
    """
    Validate a JWT token using configured API authentication settings.

    Args:
        token: JWT token string to validate.
        config: ``ConfigManager`` (``api.auth.secret_key`` / ``api.auth.algorithm``);
            the secret falls back to ``JWT_SECRET_KEY``.

    Returns:
        Decoded JWT payload dictionary.

    Raises:
        HTTPException: 500 if no secret is configured, 401 for invalid or
            expired tokens.
    """
    secret_key = (config.get("api.auth.secret_key") if config is not None else None) or (
        os.getenv("JWT_SECRET_KEY")
    )
    if not secret_key:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="JWT secret key not configured",
        )
    algorithm = config.get("api.auth.algorithm", "HS256") if config is not None else "HS256"
    try:
        return jwt.decode(token, secret_key, algorithms=[algorithm])
    except jwt.InvalidTokenError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"Invalid authentication token: {exc}",
            headers={"WWW-Authenticate": "Bearer"},
        ) from exc


def _resolve_websocket_token(websocket: WebSocket) -> str | None:
    """Return the bearer token from the Authorization header or ``token`` query param."""
    header_token = extract_bearer_token(websocket.headers.get("Authorization"))
    if header_token:
        return header_token
    return websocket.query_params.get("token")


async def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(security),
    config: Any = Depends(get_config),
) -> dict[str, Any] | None:
    """
    Validate the JWT token and return its payload (``None`` when auth is disabled).

    Raises:
        HTTPException: 401 if the token is missing or invalid.
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
    config: Any = Depends(get_config),
) -> dict[str, Any] | None:
    """
    Validate WebSocket authentication using the same JWT rules as HTTP.

    Raises:
        WebSocketException: If authentication is enabled and the token is
            missing or invalid.
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
    credentials: HTTPAuthorizationCredentials | None = Depends(security),
    config: Any = Depends(get_config),
) -> dict[str, Any] | None:
    """
    Optional authentication: the token payload, or ``None`` for anonymous access.

    Invalid tokens are treated as anonymous; enforcement happens in
    :class:`~postparse.api.middleware.AuthenticationMiddleware`.
    """
    if not isinstance(credentials, HTTPAuthorizationCredentials):
        return None
    if not _is_auth_enabled(config):
        return None
    try:
        return validate_jwt_token(credentials.credentials, config)
    except HTTPException:
        return None


# ---------------------------------------------------------------------------
# Classifiers of the legacy /classify endpoints
# ---------------------------------------------------------------------------

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
ClassifierFactory = Callable[[TaxonomySpec, str | None], TaxonomyClassifier]


def get_classifier_factory(
    service: ClassificationService = Depends(get_classification_service),
) -> ClassifierFactory:
    """Return a factory building (cached) classifiers through the shared service."""

    def factory(spec: TaxonomySpec, provider_name: str | None = None) -> TaxonomyClassifier:
        return service.classifier_for(spec, (provider_name or "").strip() or None)

    return factory


def get_taxonomies(
    service: ClassificationService = Depends(get_classification_service),
) -> dict[str, TaxonomySpec]:
    """Return the configured taxonomies (``topics`` fallback included)."""
    return dict(service.taxonomies)

