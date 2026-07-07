"""Unit tests for health router metrics behavior.

These tests validate that the `/metrics` endpoint handler computes database
totals using dedicated COUNT queries instead of loading paginated row lists.
"""

from typing import Any, Dict, cast

import pytest

from backend.postparse.api.routers.health import get_metrics
from backend.postparse.core.utils.config import ConfigManager


class _CountOnlyDatabase:
    """Database stub that supports counts and rejects row fetches.

    Args:
        instagram_total: Total Instagram posts to return from count query.
        telegram_total: Total Telegram messages to return from count query.
    """

    def __init__(self, instagram_total: int, telegram_total: int) -> None:
        """Initialize count values for the stub.

        Args:
            instagram_total: Instagram posts count.
            telegram_total: Telegram messages count.
        """
        self.instagram_total = instagram_total
        self.telegram_total = telegram_total

    def count_instagram_posts(self) -> int:
        """Return the configured Instagram count.

        Returns:
            Total number of Instagram posts.
        """
        return self.instagram_total

    def count_telegram_messages(self) -> int:
        """Return the configured Telegram count.

        Returns:
            Total number of Telegram messages.
        """
        return self.telegram_total

    def get_instagram_posts(self, limit: int = 1000) -> list[Dict[str, Any]]:
        """Fail if row-fetch API is called.

        Args:
            limit: Maximum number of posts requested.

        Returns:
            This method never returns.

        Raises:
            AssertionError: Always, because this API should not be used.
        """
        _ = limit
        raise AssertionError("metrics should not fetch instagram rows")

    def get_telegram_messages(self, limit: int = 1000) -> list[Dict[str, Any]]:
        """Fail if row-fetch API is called.

        Args:
            limit: Maximum number of messages requested.

        Returns:
            This method never returns.

        Raises:
            AssertionError: Always, because this API should not be used.
        """
        _ = limit
        raise AssertionError("metrics should not fetch telegram rows")


class TestHealthMetrics:
    """Tests for metrics aggregation in the health router."""

    @pytest.mark.asyncio
    async def test_get_metrics_uses_database_count_queries(self) -> None:
        """Use count methods to return uncapped totals.

        Example:
            When database totals exceed 1000, metrics should still return the
            full values from count queries.
        """
        db = _CountOnlyDatabase(instagram_total=2501, telegram_total=9876)

        metrics = await get_metrics(
            db=cast(Any, db),
            config=cast(ConfigManager, object()),
        )

        assert metrics["database"]["instagram_posts"] == 2501
        assert metrics["database"]["telegram_messages"] == 9876
