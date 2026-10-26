"""Tests for core.timeutil and core.urls."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import pytest

from postparse.core.timeutil import from_db_ts, is_db_ts, to_db_ts, utcnow_ts
from postparse.core.urls import extract_urls, normalize_url, url_domain

BERLIN = ZoneInfo("Europe/Berlin")


class TestTimeutil:
    @pytest.mark.parametrize(
        ("value", "expected"),
        [
            ("2024-01-15T10:00:00Z", "2024-01-15T10:00:00.000Z"),
            ("2024-01-15T10:00:00+00:00", "2024-01-15T10:00:00.000Z"),
            ("2024-01-15T12:00:00+02:00", "2024-01-15T10:00:00.000Z"),
            ("2024-01-15T10:00:00.123456z", "2024-01-15T10:00:00.123Z"),
            (datetime(2024, 1, 15, 10, tzinfo=UTC), "2024-01-15T10:00:00.000Z"),
            (datetime(2024, 1, 15, 5, tzinfo=timezone(timedelta(hours=-5))),
             "2024-01-15T10:00:00.000Z"),
        ],
    )
    def test_aware_inputs(self, value: object, expected: str) -> None:
        assert to_db_ts(value) == expected  # type: ignore[arg-type]

    def test_naive_requires_assume_tz(self) -> None:
        for naive in ("2024-01-15 10:00:00", "2024-01-15T10:00:00", datetime(2024, 1, 15)):
            with pytest.raises(ValueError, match="assume_tz"):
                to_db_ts(naive)  # type: ignore[arg-type]

    def test_naive_with_zone_handles_dst(self) -> None:
        assert to_db_ts("2024-01-15 10:00:00", assume_tz=BERLIN) == "2024-01-15T09:00:00.000Z"
        assert to_db_ts("2024-07-15 10:00:00", assume_tz=BERLIN) == "2024-07-15T08:00:00.000Z"
        assert to_db_ts(date(2024, 7, 15), assume_tz=UTC) == "2024-07-15T00:00:00.000Z"

    def test_assume_tz_ignored_for_aware(self) -> None:
        assert to_db_ts("2024-01-15T10:00:00Z", assume_tz=BERLIN) == "2024-01-15T10:00:00.000Z"

    def test_invalid(self) -> None:
        for bad in ("", "yesterday", "2024-13-01T00:00:00Z"):
            with pytest.raises(ValueError):
                to_db_ts(bad)
        with pytest.raises(TypeError):
            to_db_ts(12345)  # type: ignore[arg-type]

    def test_roundtrip_and_ordering(self) -> None:
        now = utcnow_ts()
        assert is_db_ts(now)
        parsed = from_db_ts(now)
        assert parsed.tzinfo is not None and to_db_ts(parsed) == now
        earlier = to_db_ts(datetime(1999, 12, 31, 23, 59, 59, 999000, tzinfo=UTC))
        assert earlier < now  # lexicographic == chronological
        with pytest.raises(ValueError):
            from_db_ts("2024-01-15T10:00:00Z")


class TestUrls:
    def test_extract_strips_punctuation_and_brackets(self) -> None:
        text = (
            "Recipe: https://ex.com/a, also (see https://ex.com/b_(c)) and "
            "https://ex.com/d?x=1. Done! http://plain.org"
        )
        assert extract_urls(text) == [
            "https://ex.com/a", "https://ex.com/b_(c)", "https://ex.com/d?x=1", "http://plain.org"
        ]
        assert extract_urls(None) == []
        assert extract_urls("ftp://nope.org and https:// nothing") == []

    def test_extract_deduplicates(self) -> None:
        assert extract_urls("https://a.com https://a.com") == ["https://a.com"]

    def test_normalize(self) -> None:
        url = ("HTTPS://WWW.Example.COM:443/Path/To?utm_source=ig&b=2&igsh=xyz&a=1&si=s"
               "&fbclid=f&gclid=g&ref_src=r&igshid=i&a=0#frag")
        assert normalize_url(url) == "https://www.example.com/Path/To?a=1&a=0&b=2"
        assert normalize_url("http://ex.com") == "http://ex.com/"
        assert normalize_url("http://ex.com:8080/x") == "http://ex.com:8080/x"
        assert normalize_url("https://ex.com/x?b=1&a=2") == normalize_url(
            "https://ex.com/x?a=2&b=1"
        )
        with pytest.raises(ValueError):
            normalize_url("mailto:a@b.c")

    @pytest.mark.parametrize(
        ("url", "domain"),
        [
            ("https://www.youtube.com/watch?v=1", "youtube.com"),
            ("https://m.youtube.com/watch", "youtube.com"),
            ("https://news.bbc.co.uk/x", "bbc.co.uk"),
            ("https://localhost:8000/", "localhost"),
            ("http://192.168.1.10/a", "192.168.1.10"),
            ("https://WWW.Example.org", "example.org"),
        ],
    )
    def test_domain(self, url: str, domain: str) -> None:
        assert url_domain(url) == domain
