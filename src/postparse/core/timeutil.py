"""Canonical timestamp handling for the PostParse database.

Every timestamp stored by the schema v2 database is UTC text in the form
``YYYY-MM-DDTHH:MM:SS.sssZ`` (millisecond precision, literal ``Z``). This format
sorts lexicographically in chronological order, which is what makes string
comparison and indexes on timestamp columns correct.

Example:
    >>> from zoneinfo import ZoneInfo
    >>> to_db_ts("2024-01-15 10:00:00", assume_tz=ZoneInfo("Europe/Berlin"))
    '2024-01-15T09:00:00.000Z'
"""

from __future__ import annotations

import re
from datetime import UTC, date, datetime, time, tzinfo

__all__ = [
    "DB_TS_PATTERN",
    "from_db_ts",
    "is_db_ts",
    "to_db_ts",
    "utcnow_ts",
]

#: Regular expression matching the canonical database timestamp format.
DB_TS_PATTERN = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}Z$")

TimestampInput = datetime | date | str


def _format(value: datetime) -> str:
    """Format an aware datetime as canonical UTC text."""
    utc = value.astimezone(UTC)
    return utc.strftime("%Y-%m-%dT%H:%M:%S.") + f"{utc.microsecond // 1000:03d}Z"


def utcnow_ts() -> str:
    """Return the current UTC time as a canonical database timestamp.

    Returns:
        Timestamp text such as ``2026-10-26T12:00:00.123Z``.
    """
    return _format(datetime.now(UTC))


def is_db_ts(value: str) -> bool:
    """Return True if ``value`` is already in canonical database format."""
    return bool(DB_TS_PATTERN.match(value))


def _parse_string(text: str) -> datetime:
    """Parse an ISO-8601-like string (``Z``, offsets, naive, space separator)."""
    cleaned = text.strip()
    if not cleaned:
        raise ValueError("Empty timestamp string")
    if cleaned[-1] in "zZ":
        cleaned = cleaned[:-1] + "+00:00"
    try:
        return datetime.fromisoformat(cleaned)
    except ValueError as exc:
        raise ValueError(f"Unrecognised timestamp: {text!r}") from exc


def to_db_ts(value: TimestampInput, assume_tz: tzinfo | None = None) -> str:
    """Convert a datetime, date or ISO string to a canonical database timestamp.

    Args:
        value: Aware or naive ``datetime``, a ``date`` (interpreted as midnight),
            or an ISO-8601 string. Strings may end in ``Z``, carry an offset such
            as ``+00:00``, be naive, and use either ``T`` or a space separator.
        assume_tz: Time zone used to interpret naive values (for example
            ``ZoneInfo("UTC")`` or ``ZoneInfo("Europe/Berlin")``). Required when
            ``value`` carries no offset; ignored for aware values.

    Returns:
        Canonical UTC timestamp text (``YYYY-MM-DDTHH:MM:SS.sssZ``).

    Raises:
        ValueError: If the value cannot be parsed, or is naive and no
            ``assume_tz`` was given.
        TypeError: If ``value`` has an unsupported type.
    """
    if isinstance(value, str):
        parsed = _parse_string(value)
    elif isinstance(value, datetime):
        parsed = value
    elif isinstance(value, date):
        parsed = datetime.combine(value, time.min)
    else:
        raise TypeError(f"Unsupported timestamp type: {type(value).__name__}")

    if parsed.tzinfo is None or parsed.tzinfo.utcoffset(parsed) is None:
        if assume_tz is None:
            raise ValueError(f"Naive timestamp {value!r} needs an explicit assume_tz to be stored")
        parsed = parsed.replace(tzinfo=assume_tz)
    return _format(parsed)


def from_db_ts(text: str) -> datetime:
    """Parse a canonical database timestamp into an aware UTC datetime.

    Args:
        text: Timestamp in canonical format.

    Returns:
        Aware ``datetime`` in UTC.

    Raises:
        ValueError: If ``text`` is not in canonical format.
    """
    if not isinstance(text, str) or not is_db_ts(text):
        raise ValueError(f"Not a canonical database timestamp: {text!r}")
    return datetime.fromisoformat(text[:-1] + "+00:00")
