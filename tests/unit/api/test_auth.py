"""JWT authentication: dependency functions and the middleware (HS256)."""

from __future__ import annotations

import time
from typing import Any

import jwt
import pytest
from fastapi import FastAPI, HTTPException
from fastapi.security import HTTPAuthorizationCredentials
from fastapi.testclient import TestClient

from postparse.api.dependencies import (
    extract_bearer_token,
    get_current_user,
    get_optional_auth,
    validate_jwt_token,
)
from postparse.api.middleware import AuthenticationMiddleware

SECRET = "unit-test-secret-padded-to-32-bytes-min"


class StaticConfig:
    """Minimal ``ConfigManager`` stand-in."""

    def __init__(self, **values: Any) -> None:
        self.values = {"api.auth.enabled": True, "api.auth.secret_key": SECRET,
                       "api.auth.algorithm": "HS256", **values}

    def get(self, key: str, default: Any = None, env_var: str | None = None) -> Any:
        return self.values.get(key, default)


def make_token(secret: str = SECRET, exp_offset: int = 300, **claims: Any) -> str:
    payload = {"sub": "tester", "exp": int(time.time()) + exp_offset, **claims}
    return jwt.encode(payload, secret, algorithm="HS256")


def bearer(token: str) -> HTTPAuthorizationCredentials:
    return HTTPAuthorizationCredentials(scheme="Bearer", credentials=token)


class TestValidateToken:
    def test_valid_token(self) -> None:
        payload = validate_jwt_token(make_token(role="admin"), StaticConfig())
        assert payload["sub"] == "tester" and payload["role"] == "admin"

    def test_expired_token_is_401(self) -> None:
        with pytest.raises(HTTPException) as exc:
            validate_jwt_token(make_token(exp_offset=-60), StaticConfig())
        assert exc.value.status_code == 401
        assert exc.value.headers == {"WWW-Authenticate": "Bearer"}

    @pytest.mark.parametrize("token", ["garbage", make_token(secret="other-secret-padded-to-32-bytes-minimum")])
    def test_invalid_tokens_are_401(self, token: str) -> None:
        with pytest.raises(HTTPException) as exc:
            validate_jwt_token(token, StaticConfig())
        assert exc.value.status_code == 401

    def test_missing_secret_is_500(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("JWT_SECRET_KEY", raising=False)
        with pytest.raises(HTTPException) as exc:
            validate_jwt_token(make_token(), StaticConfig(**{"api.auth.secret_key": None}))
        assert exc.value.status_code == 500

    def test_secret_from_environment(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("JWT_SECRET_KEY", "env-secret-padded-to-32-bytes-minimum")
        token = make_token(secret="env-secret-padded-to-32-bytes-minimum")
        assert validate_jwt_token(token, None)["sub"] == "tester"

    @pytest.mark.parametrize(
        ("header", "expected"),
        [("Bearer abc", "abc"), ("Bearer ", None), ("Basic abc", None), (None, None)],
    )
    def test_extract_bearer_token(self, header: str | None, expected: str | None) -> None:
        assert extract_bearer_token(header) == expected


class TestDependencies:
    async def test_current_user_disabled(self) -> None:
        assert await get_current_user(None, StaticConfig(**{"api.auth.enabled": False})) is None
        assert await get_current_user(None, None) is None

    async def test_current_user_requires_token(self) -> None:
        with pytest.raises(HTTPException) as exc:
            await get_current_user(None, StaticConfig())
        assert exc.value.status_code == 401

    async def test_current_user_returns_payload(self) -> None:
        user = await get_current_user(bearer(make_token()), StaticConfig())
        assert user["sub"] == "tester"

    def test_optional_auth(self) -> None:
        assert get_optional_auth(bearer(make_token()), StaticConfig())["sub"] == "tester"
        assert get_optional_auth(bearer("garbage"), StaticConfig()) is None
        assert get_optional_auth(None, StaticConfig()) is None


class TestMiddleware:
    @pytest.fixture
    def client(self) -> TestClient:
        app = FastAPI()
        app.add_middleware(AuthenticationMiddleware, config=StaticConfig())

        @app.get("/health")
        def health() -> dict[str, str]:
            return {"status": "ok"}

        @app.get("/private")
        def private() -> dict[str, str]:
            return {"status": "secret"}

        return TestClient(app)

    def test_public_path_without_token(self, client: TestClient) -> None:
        assert client.get("/health").status_code == 200

    def test_private_path_needs_token(self, client: TestClient) -> None:
        response = client.get("/private")
        assert response.status_code == 401
        assert response.json()["error_code"] == "UNAUTHORIZED"

    def test_valid_expired_invalid(self, client: TestClient) -> None:
        ok = client.get("/private", headers={"Authorization": f"Bearer {make_token()}"})
        assert ok.status_code == 200
        expired = client.get(
            "/private", headers={"Authorization": f"Bearer {make_token(exp_offset=-5)}"}
        )
        assert expired.status_code == 401
        invalid = client.get("/private", headers={"Authorization": "Bearer nope"})
        assert invalid.status_code == 401
