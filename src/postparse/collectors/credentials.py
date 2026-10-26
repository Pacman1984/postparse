"""Credentials for the collectors, read from environment variables.

The CLI loads ``config/.env`` into the environment before commands run. Values
are never logged; the dataclasses hide secrets from ``repr``.

Variables:
    ``TELEGRAM_API_ID``, ``TELEGRAM_API_HASH``, ``TELEGRAM_PHONE`` (optional),
    ``INSTAGRAM_USERNAME``, ``INSTAGRAM_PASSWORD`` (optional when a valid
    session file exists).
"""

from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass, field

from postparse.collectors.base import CredentialsMissing

__all__ = [
    "InstagramCredentials",
    "TelegramCredentials",
    "instagram_credentials",
    "telegram_credentials",
]


@dataclass(frozen=True, slots=True)
class TelegramCredentials:
    """Telegram API credentials (``api_hash`` and ``phone`` hidden from repr)."""

    api_id: int
    api_hash: str = field(repr=False)
    phone: str | None = field(default=None, repr=False)


@dataclass(frozen=True, slots=True)
class InstagramCredentials:
    """Instagram login (``password`` hidden from repr)."""

    username: str
    password: str | None = field(default=None, repr=False)


def _get(env: Mapping[str, str], name: str) -> str | None:
    value = env.get(name)
    if value is None:
        return None
    value = value.strip()
    return value or None


def telegram_credentials(env: Mapping[str, str] | None = None) -> TelegramCredentials:
    """Read Telegram credentials from the environment.

    Args:
        env: Mapping to read (default ``os.environ``).

    Returns:
        Credentials.

    Raises:
        CredentialsMissing: If ``TELEGRAM_API_ID`` or ``TELEGRAM_API_HASH`` is
            missing, or the API id is not a number.
    """
    env = os.environ if env is None else env
    api_id = _get(env, "TELEGRAM_API_ID")
    api_hash = _get(env, "TELEGRAM_API_HASH")
    missing = tuple(
        name for name, value in (("TELEGRAM_API_ID", api_id), ("TELEGRAM_API_HASH", api_hash))
        if value is None
    )
    if missing:
        raise CredentialsMissing("Telegram", missing)
    assert api_id is not None and api_hash is not None
    try:
        numeric_id = int(api_id)
    except ValueError:
        raise CredentialsMissing("Telegram", ("TELEGRAM_API_ID (numeric)",)) from None
    return TelegramCredentials(numeric_id, api_hash, _get(env, "TELEGRAM_PHONE"))


def instagram_credentials(
    env: Mapping[str, str] | None = None, username: str | None = None
) -> InstagramCredentials:
    """Read Instagram credentials from the environment.

    Args:
        env: Mapping to read (default ``os.environ``).
        username: Explicit username overriding ``INSTAGRAM_USERNAME``.

    Returns:
        Credentials (``password`` may be ``None``; a saved session can suffice).

    Raises:
        CredentialsMissing: If no username is available.
    """
    env = os.environ if env is None else env
    user = (username or "").strip() or _get(env, "INSTAGRAM_USERNAME")
    if user is None:
        raise CredentialsMissing("Instagram", ("INSTAGRAM_USERNAME",))
    return InstagramCredentials(user, _get(env, "INSTAGRAM_PASSWORD"))
