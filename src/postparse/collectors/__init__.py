"""Collectors that read saved content from Telegram and Instagram into schema v2.

See :mod:`postparse.collectors.telegram` and :mod:`postparse.collectors.instagram`;
:class:`postparse.services.extraction.ExtractionService` is the usual entry point.
"""

from postparse.collectors.base import (
    AuthRequired,
    CollectorError,
    CollectStats,
    CredentialsMissing,
    InstagramAuthRequired,
    InstagramFeedUnavailable,
    InstagramRateLimited,
    InstagramSessionCheckFailed,
    ProgressCallback,
    ProgressEvent,
    RateLimited,
    TelegramAuthRequired,
    TelegramRateLimited,
)
from postparse.collectors.credentials import (
    InstagramCredentials,
    TelegramCredentials,
    instagram_credentials,
    telegram_credentials,
)

__all__ = [
    "AuthRequired",
    "CollectStats",
    "CollectorError",
    "CredentialsMissing",
    "InstagramAuthRequired",
    "InstagramCredentials",
    "InstagramFeedUnavailable",
    "InstagramRateLimited",
    "InstagramSessionCheckFailed",
    "ProgressCallback",
    "ProgressEvent",
    "RateLimited",
    "TelegramAuthRequired",
    "TelegramCredentials",
    "TelegramRateLimited",
    "instagram_credentials",
    "telegram_credentials",
]
