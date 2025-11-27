"""
Tests for API dependency injection functions.

This module tests the FastAPI dependencies for database connections,
classifiers, and authentication.
"""

import pytest
from unittest.mock import Mock, patch, MagicMock
from fastapi import HTTPException

from backend.postparse.api.dependencies import (
    get_config,
    get_db,
    get_recipe_llm_classifier,
    get_current_user,
    get_optional_auth,
)
from backend.postparse.core.utils.config import ConfigManager
from backend.postparse.core.data.database import SocialMediaDatabase
from backend.postparse.services.analysis.classifiers.llm import RecipeLLMClassifier


class TestGetConfig:
    """Test configuration dependency."""

    def test_get_config_returns_singleton(self):
        """Test that get_config returns a singleton instance."""
        config1 = get_config()
        config2 = get_config()
        
        assert config1 is config2
        assert isinstance(config1, ConfigManager)


class TestGetDb:
    """Test database dependency."""

    def test_get_db_yields_database_instance(self):
        """Test that get_db yields a database instance."""
        with patch('backend.postparse.api.dependencies.get_config') as mock_config:
            mock_config.return_value = Mock(get=Mock(return_value="test.db"))
            
            db_generator = get_db(mock_config.return_value)
            db = next(db_generator)
            
            assert isinstance(db, SocialMediaDatabase)
            
            # Cleanup
            try:
                next(db_generator)
            except StopIteration:
                pass


class TestGetRecipeLlmClassifier:
    """Test classifier dependency."""

    @patch('backend.postparse.api.dependencies.RecipeLLMClassifier')
    def test_get_classifier_returns_cached_instance(self, mock_classifier):
        """Test that classifier is cached."""
        mock_classifier.return_value = Mock(spec=RecipeLLMClassifier)
        mock_config = Mock(get=Mock(return_value="ollama"))
        
        # First call
        classifier1 = get_recipe_llm_classifier(mock_config)
        # Second call
        classifier2 = get_recipe_llm_classifier(mock_config)
        
        # Should return same instance
        assert classifier1 is classifier2


class TestGetCurrentUser:
    """Test authentication dependency."""

    @pytest.mark.asyncio
    async def test_get_current_user_when_auth_disabled(self):
        """Test that get_current_user returns None when auth is disabled."""
        mock_config = Mock(get=Mock(return_value=False))
        
        user = await get_current_user(None, mock_config)
        
        assert user is None

    @pytest.mark.asyncio
    async def test_get_current_user_raises_when_no_token(self):
        """Test that get_current_user raises HTTPException when no token is provided."""
        mock_config = Mock(get=Mock(side_effect=lambda x, y=None: True if x == "api.auth.enabled" else y))
        
        with pytest.raises(HTTPException) as exc_info:
            await get_current_user(None, mock_config)
        
        assert exc_info.value.status_code == 401

    @pytest.mark.asyncio
    async def test_get_current_user_validates_token(self):
        """Test that get_current_user validates JWT token."""
        from fastapi.security import HTTPAuthorizationCredentials
        
        mock_credentials = Mock(spec=HTTPAuthorizationCredentials)
        mock_credentials.credentials = "valid_token"
        
        mock_config = Mock()
        mock_config.get = Mock(side_effect=lambda x, y=None: {
            "api.auth.enabled": True,
            "api.auth.secret_key": "test_secret",
            "api.auth.algorithm": "HS256"
        }.get(x, y))
        
        with patch('backend.postparse.api.dependencies.jwt') as mock_jwt:
            mock_jwt.decode.return_value = {"username": "test_user"}
            
            user = await get_current_user(mock_credentials, mock_config)
            
            assert user == {"username": "test_user"}


class TestGetOptionalAuth:
    """Test optional authentication dependency."""

    def test_get_optional_auth_returns_user(self):
        """Test that get_optional_auth returns user info if authenticated."""
        mock_user = {"username": "test_user"}
        
        result = get_optional_auth(mock_user)
        
        assert result == mock_user

    def test_get_optional_auth_returns_none(self):
        """Test that get_optional_auth returns None if not authenticated."""
        result = get_optional_auth(None)
        
        assert result is None

