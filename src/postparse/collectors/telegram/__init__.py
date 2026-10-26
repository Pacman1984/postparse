"""Telegram "Saved Messages" collector (Telethon)."""

from postparse.collectors.telegram.collector import (
    TelegramCollector,
    TelegramOptions,
    resolve_session_path,
)

__all__ = ["TelegramCollector", "TelegramOptions", "resolve_session_path"]
