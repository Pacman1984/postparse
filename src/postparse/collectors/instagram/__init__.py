"""Instagram saved-posts collector (instaloader)."""

from postparse.collectors.instagram.collector import (
    InstagramCollector,
    InstagramOptions,
    InvalidSessionCookie,
    parse_sessionid,
    resolve_session_path,
)

__all__ = [
    "InstagramCollector",
    "InstagramOptions",
    "InvalidSessionCookie",
    "parse_sessionid",
    "resolve_session_path",
]
