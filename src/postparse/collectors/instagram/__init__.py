"""Instagram saved-posts collector (instaloader)."""

from postparse.collectors.instagram.collector import (
    InstagramCollector,
    InstagramOptions,
    resolve_session_path,
)

__all__ = ["InstagramCollector", "InstagramOptions", "resolve_session_path"]
